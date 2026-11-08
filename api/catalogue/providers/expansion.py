"""Fail-closed, content-addressed overlay. Absence alone preserves the base."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .abo import StrictModel, SeedProduct, AssetManifest, entry_from_manifest, ROOT, BUNDLED_MANIFEST_DIR

PROFILE = "catalogue-expansion-v1"
INDEX_POLICY = "catalogue-expansion-index-v1"
METADATA_SHA256 = "660f4d01bf817802c4fc664e848af12b72246efdb15324ad1d0d2bce33f54fe9"
HASH = r"^[a-f0-9]{64}$"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class CatalogueExpansionError(ValueError):
    pass


class FilePin(StrictModel):
    file: str = Field(pattern=r"^(?:asset-manifest\.json|lod[012]\.(?:bin|gltf)|textures/[a-zA-Z0-9_.-]+\.ktx2)$")
    bytes: int = Field(gt=0, strict=True)
    sha256: str = Field(pattern=HASH)


class ExpansionEntry(StrictModel):
    record: SeedProduct
    rooms: tuple[Literal["bedroom", "living-room"], ...] = Field(min_length=1, max_length=2)
    files: tuple[FilePin, ...] = Field(min_length=8, max_length=64)
    reviewSha256: str = Field(pattern=HASH)
    conversionSha256: str = Field(pattern=HASH)

    @model_validator(mode="after")
    def valid(self):
        r = self.record
        model = r.sourcePath.split("/")[1][:-4]
        if r.sourcePath != f"{model[-1]}/{model}.glb" or r.sourceBytes > 100_000_000:
            raise ValueError("Invalid bounded official source")
        if len(set(self.rooms)) != len(self.rooms) or len(set(r.privateStyleIds)) != len(r.privateStyleIds) or not set(r.privateStyleIds) <= {f"style-{i:02}" for i in range(1, 6)}:
            raise ValueError("Invalid Room Types or Styles")
        rooms = {"bedroom"} if r.category in {"bed", "nightstand", "wardrobe", "dresser"} else {"living-room"} if r.category in {"sofa", "table"} else {"bedroom", "living-room"}
        if not set(self.rooms) <= rooms:
            raise ValueError("Category incompatible with Room Type")
        if r.placementClass != ("floor-covering" if r.category == "rug" else "floor-standing"):
            raise ValueError("Only reviewed rugs can be floor coverings")
        if len(set(r.wallContactFaces)) != len(r.wallContactFaces) or not set(r.wallContactFaces) <= {"left", "right", "back"}:
            raise ValueError("Unsupported wall contact")
        faces = {a.face for a in r.accessRegions}
        required = {"left", "right", "front"} if r.category == "bed" else set() if r.category in {"rug", "lamp"} else {"front"}
        if len(faces) != len(r.accessRegions) or not required <= faces or faces & set(r.wallContactFaces) or any(not a.required or not 0.6 <= a.depthM <= 2 or not a.purpose.strip() for a in r.accessRegions):
            raise ValueError("Missing/conflicting functional access")
        if r.category == "rug" and (r.wallContactFaces or r.accessRegions):
            raise ValueError("Rug metadata incompatible")
        names = {f.file for f in self.files}
        needed = {"asset-manifest.json", *(f"lod{i}.{ext}" for i in range(3) for ext in ("bin", "gltf"))}
        if len(names) != len(self.files) or not needed <= names or sum(f.bytes for f in self.files if f.file != "asset-manifest.json") >= 5_000_000:
            raise ValueError("Invalid Product file union/budget")
        return self


class Review(StrictModel):
    actor: Literal["agent"]
    reviewerIdentity: str = Field(min_length=1, max_length=4000)
    purpose: str = Field(min_length=1, max_length=4000)
    evidenceKind: Literal["genuine-agent-curation"]
    evidenceSha256: str = Field(pattern=HASH)


class ExpansionBatch(StrictModel):
    schemaVersion: Literal[1]
    profile: Literal["catalogue-expansion-v1"]
    batchId: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    intakeSha256: str = Field(pattern=HASH)
    metadataSha256: Literal[METADATA_SHA256]
    review: Review
    curatedOn: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    entries: tuple[ExpansionEntry, ...] = Field(min_length=1, max_length=50)


class ExpansionIndex(StrictModel):
    schemaVersion: Literal[1]
    policyVersion: Literal["catalogue-expansion-index-v1"]
    baseVersion: str
    batches: tuple[str, ...] = Field(min_length=1, max_length=100)


def safe_read(file: Path):
    for p in (file, *file.parents):
        if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
            raise ValueError("Linked publication path")
    return file.read_bytes()


def pinned(file, pin):
    raw = safe_read(file)
    if len(raw) != pin.bytes or digest(raw) != pin.sha256:
        raise ValueError("Published bytes changed")
    return raw


def expanded_entries(base, base_version, base_records, *, root=ROOT):
    directory = root / "api/catalogue/providers/expansion"
    index_file = directory / "index.json"
    if not index_file.exists() and not index_file.is_symlink():
        return base, base_version
    try:
        index = ExpansionIndex.model_validate_json(safe_read(index_file))
        if index.baseVersion != base_version or len(set(index.batches)) != len(index.batches):
            raise ValueError("Base/index identity drift")
        batches = []
        for h in index.batches:
            import re
            if not re.fullmatch(HASH, h):
                raise ValueError("Invalid batch digest")
            raw = safe_read(directory / f"{h}.json")
            b = ExpansionBatch.model_validate_json(raw)
            if digest(raw) != h or raw.decode() != canonical(json.loads(raw)):
                raise ValueError("Batch digest/canonical identity drift")
            batches.append(b)
        if len({b.batchId for b in batches}) != len(batches):
            raise ValueError("Repeated batch ID")
        records = [*base_records, *(e.record for b in batches for e in b.entries)]
        for field in ("productId", "itemId", "sourcePath", "sourceSha256"):
            if len({getattr(r, field) for r in records}) != len(records):
                raise ValueError(f"Global duplicate {field}")
        entries = list(base)
        for b in batches:
            for e in b.entries:
                product_dir = root / "public/products" / e.record.productId
                if product_dir.exists():
                    actual = set()
                    for f in product_dir.rglob("*"):
                        if f.is_symlink() or (hasattr(f,"is_junction") and f.is_junction()):
                            raise ValueError("Linked asset")
                        if f.is_dir() and f != product_dir / 'textures':
                            raise ValueError('Unknown asset directory')
                        if f.is_file():
                            actual.add(f.relative_to(product_dir).as_posix())
                    if actual != {f.file for f in e.files}:
                        raise ValueError("File union drift")
                    raw_manifest = None
                    for f in e.files:
                        data = pinned(product_dir / f.file, f)
                        if f.file == "asset-manifest.json":
                            raw_manifest = data
                else:
                    # Vercel function carries manifests; static assets remain in dist.
                    manifest_pin = next(f for f in e.files if f.file == "asset-manifest.json")
                    raw_manifest = pinned(root / "api/catalogue/providers/manifests" / f"{e.record.productId}.json", manifest_pin)
                manifest = AssetManifest.model_validate_json(raw_manifest)
                entries.append(entry_from_manifest(e.record, manifest, room_types=e.rooms, curated_on=b.curatedOn))
        version = base_version + "+expansion-" + digest(canonical(index.model_dump(mode="json")).encode())
        return tuple(entries), version
    except (ValueError, OSError, KeyError, StopIteration) as error:
        raise CatalogueExpansionError(f"Configured Catalogue expansion is invalid: {error}") from error
