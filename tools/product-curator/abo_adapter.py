"""Local-only ABO boundary. Stdout contains only validated neutral Catalogue data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.catalogue.contract import CatalogueEntry, CatalogueQuery
from api.catalogue.providers.abo import AssetManifest, SeedCatalogue, LivingCandidateCatalogue, entry_from_manifest
from api.catalogue.static import StaticCatalogue
from api.models import Product


def main(data: dict) -> object:
    mode = data["mode"]
    seed_type = LivingCandidateCatalogue if data.get("profile") == "living-seed-v1" else SeedCatalogue
    if mode == "seed":
        return seed_type.model_validate(data["seed"]).model_dump(mode="json")
    if mode == "project":
        seed = seed_type.model_validate(data["seed"])
        record = next(p for p in seed.products if p.productId == data["productId"])
        styles = tuple(data["styles"])
        rooms = tuple(data["rooms"])
        if not styles or len(styles) != len(set(styles)) or not set(styles) <= {s.id for s in seed.styleVocabulary.styles}:
            raise ValueError("Choose unique known private Styles")
        if data.get("profile") == "living-seed-v1" and rooms != ("living-room",):
            raise ValueError("The living seed promotion scope requires an explicit Living room tag only")
        if not rooms or len(rooms) != len(set(rooms)) or not set(rooms) <= {"bedroom", "living-room"}:
            raise ValueError("Choose unique known Room Types")
        entry = entry_from_manifest(
            record, AssetManifest.model_validate(data["manifest"]),
            room_types=rooms, private_style_ids=styles, mesh_base_url=data["meshBase"], curated_on=seed.curatedOn,
        )
        StaticCatalogue("local-curation-v1", [entry])
        return {"product": entry.product.model_dump(mode="json"), "privateStyleIds": list(entry.private_style_ids)}
    if mode == "catalogue":
        entries = tuple(CatalogueEntry(Product.model_validate(e["product"]), tuple(e["privateStyleIds"])) for e in data["entries"])
        catalogue = StaticCatalogue("local-curation-v1", entries)
        query = data.get("query", {})
        if set(query) - {"roomType", "category", "privateStyleId"}:
            raise ValueError("Unknown Catalogue query")
        if query.get("roomType") not in (None, "bedroom", "living-room"):
            raise ValueError("Unknown Room Type")
        return [p.model_dump(mode="json") for p in catalogue.list(CatalogueQuery(
            room_type=query.get("roomType"), category=query.get("category"), private_style_id=query.get("privateStyleId"),
        ))]
    raise ValueError("Unknown local adapter operation")


if __name__ == "__main__":
    print(json.dumps(main(json.load(sys.stdin)), allow_nan=False, separators=(",", ":")))
