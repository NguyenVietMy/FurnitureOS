"""Explicit, sanitized account/capability probe. Never run without owner authorization."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.catalogue import catalogue  # noqa: E402
from api.catalogue.contract import CatalogueQuery  # noqa: E402
from api.design import intent_fixture_room  # noqa: E402
from api.live_generation import (  # noqa: E402
    SelectionRejected,
    _output_schema,
    _prompt,
    _validated_selection,
    _wall_capability_map,
    reference_manifest,
    verified_reference,
)
from api.provider import AnthropicProvider, MODEL_ID, ProviderCallError, ProviderSettings  # noqa: E402
from api.zones import derive_zones  # noqa: E402
from scripts.ticket6_evidence import files_digest, source_files  # noqa: E402


def safe_metadata(value: dict) -> dict:
    capabilities = value.get("capabilities") if isinstance(value.get("capabilities"), dict) else {}
    return {
        "id": value.get("id"),
        "displayName": value.get("display_name"),
        "createdAt": value.get("created_at"),
        "capabilities": capabilities,
    }


def write_json(path: Path, value: dict) -> None:
    resolved = path.expanduser().resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise SystemExit("Probe evidence must be written outside the repository.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, resolved)


def canonical(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def source_digest() -> str:
    return files_digest(source_files())["sha256"]


def production_material(reference_id: str) -> dict:
    reference = next((item for item in reference_manifest().images if item.id == reference_id), None)
    if reference is None:
        raise SystemExit("Unknown production reference id.")
    image = verified_reference(reference)
    eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
    if not any(product.category == "bed" for product in eligible):
        raise SystemExit("Selected production reference has no eligible bed and cannot be probed.")
    room = intent_fixture_room()
    zone_offer = derive_zones(room)
    capabilities = _wall_capability_map(room, eligible)
    schema = _output_schema()
    prompt = _prompt(
        eligible=eligible,
        room=room,
        zone_offer=zone_offer,
        capabilities=capabilities,
        provider_call_index=0,
        previous=None,
        session=None,
    )
    return {
        "reference": reference,
        "image": image,
        "eligible": eligible,
        "room": room,
        "zoneOffer": zone_offer,
        "capabilities": capabilities,
        "schema": schema,
        "prompt": prompt,
    }


def production_binding(material: dict) -> dict:
    reference = material["reference"]
    schema_bytes = canonical(material["schema"])
    prompt_bytes = material["prompt"].encode("utf-8")
    return {
        "sourceSha256": source_digest(),
        "referenceId": reference.id,
        "referenceSha256": reference.sha256,
        "referenceBytes": reference.bytes,
        "promptSha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "promptBytes": len(prompt_bytes),
        "schemaSha256": hashlib.sha256(schema_bytes).hexdigest(),
        "schemaBytes": len(schema_bytes),
        "model": MODEL_ID,
        "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema", "maxTokens": 8192},
        "validation": "ProviderSelection plus shared Product/Room capabilities and graph policy",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("minimal", "production-export", "production-message"),
        default="minimal",
    )
    parser.add_argument("--reference-id", default="ref-01")
    parser.add_argument("--allow-paid-message", action="store_true")
    args = parser.parse_args()
    evidence = {
        "version": 2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "modelRequested": MODEL_ID,
        "workspaceHeaderConfigured": None,
        "paidMessageAuthorizedByCommand": args.allow_paid_message,
        "metadata": None,
        "message": None,
    }
    material = production_material(args.reference_id) if args.mode != "minimal" else None
    if material is not None:
        evidence["productionBinding"] = production_binding(material)
    if args.mode == "production-export":
        evidence["status"] = "exported-no-provider-call"
        write_json(args.output, evidence)
        return 0
    if not args.allow_paid_message:
        evidence["status"] = "blocked-no-paid-authorization"
        write_json(args.output, evidence)
        return 2
    try:
        settings = ProviderSettings.from_environment()
        evidence["workspaceHeaderConfigured"] = bool(settings.workspace_id)
        provider = AnthropicProvider(settings)
        deadline = monotonic() + 300
        metadata = provider.retrieve_model(deadline)
        evidence["metadata"] = safe_metadata(metadata)
        if material is None:
            reference = reference_manifest().images[0]
            image = verified_reference(reference)
            prompt = 'Return exactly {"ok":true}. This is a minimal authorized structured capability probe.'
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {"ok": {"type": "boolean", "const": True}},
                "required": ["ok"],
            }
        else:
            reference = material["reference"]
            image = material["image"]
            prompt = material["prompt"]
            schema = material["schema"]
        reply = provider.generate(
            prompt_text=prompt,
            image_media_type="image/jpeg",
            image_base64=base64.b64encode(image).decode("ascii"),
            output_schema=schema,
            deadline_at=deadline,
        )
        if material is None:
            schema_valid = reply.payload == {"ok": True}
            rejection = None
        else:
            try:
                _validated_selection(
                    reply.payload,
                    material["eligible"],
                    room=material["room"],
                    zone_offer=material["zoneOffer"],
                    capabilities=material["capabilities"],
                    selection_id="initial",
                    initial=None,
                )
                schema_valid = True
                rejection = None
            except SelectionRejected as error:
                schema_valid = False
                rejection = error.rejection.model_dump(mode="json")
        evidence["message"] = {
            "modelReturned": reply.model,
            "stopReason": reply.stop_reason,
            "schemaValid": schema_valid,
            "selectionRejection": rejection,
            "usage": reply.usage.model_dump(mode="json") if reply.usage else None,
            "latencyMs": reply.latency_ms,
            "referenceId": reference.id,
            "referenceSha256": reference.sha256,
            "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema"},
        }
        evidence["status"] = "passed" if evidence["message"]["schemaValid"] else "failed-schema"
    except ProviderCallError as error:
        evidence["status"] = "failed"
        evidence["error"] = {"code": error.code, "detail": error.detail, "messageAttempted": error.attempted}
    write_json(args.output, evidence)
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
