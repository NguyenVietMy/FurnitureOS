from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.catalogue import CatalogueQuery, StaticCatalogue, catalogue, dimension_evidence
from api.catalogue.providers.abo import asset_manifest
from api.design import FEATURED_PRODUCT_ID
from api.models import Product


def as_dict(product) -> dict:
    return deepcopy(product.model_dump(mode="json"))


def test_catalogue_exposes_the_curated_product(product) -> None:
    assert product.id == FEATURED_PRODUCT_ID
    assert product.category == "bed"
    assert product.roomTypes == ("bedroom",)
    assert product.placementClass == "floor-standing"
    assert product.wallContactFaces == ("back",)
    assert sorted(region.face for region in product.accessRegions) == ["front", "left", "right"]
    assert product.frontAxis == "+z"


@pytest.mark.parametrize("axis,expected", [("widthM", 1.695826), ("heightM", 1.425926), ("depthM", 2.23299)])
def test_dimensions_are_measured_metres(product, axis, expected) -> None:
    assert getattr(product.dimensionsM, axis) == pytest.approx(expected, abs=1e-6)


def test_manifest_is_the_dimensional_source_of_truth(product) -> None:
    manifest = asset_manifest()
    assert tuple(product.dimensionsM.model_dump().values()) == manifest.source.bounds.size
    assert product.mesh.normalization.frontAxis == manifest.normalization.frontAxis
    assert product.mesh.normalization.transform.translation == manifest.normalization.appliedTransform.translation


def test_purchase_unavailability_is_disclosed(product) -> None:
    assert product.purchaseUrl == ""
    assert product.purchase.availability == "unavailable"
    assert "unavailable" in product.purchase.note.lower()
    assert product.purchase.checkedOn.isoformat() == "2026-09-08"


@pytest.mark.parametrize("field", ["source", "holder", "license", "licenseUrl", "sourceUrl", "materialUrl", "citation", "modifications"])
def test_attribution_fields_are_present_and_nonblank(product, field) -> None:
    assert str(getattr(product.attribution, field)).strip()


def test_attribution_links_the_collection_and_exact_material(product) -> None:
    assert product.attribution.sourceUrl.startswith("https://")
    assert product.attribution.materialUrl == asset_manifest().source.url
    assert product.attribution.materialUrl.endswith(".glb")


def test_mesh_has_ordered_decreasing_lods(product) -> None:
    assert [lod.level for lod in product.mesh.lods] == [0, 1, 2]
    assert [lod.triangles for lod in product.mesh.lods] == sorted((lod.triangles for lod in product.mesh.lods), reverse=True)
    assert [lod.exclusiveBytes for lod in product.mesh.lods] == sorted((lod.exclusiveBytes for lod in product.mesh.lods), reverse=True)


def test_mesh_is_floor_centred_and_normalized(product) -> None:
    assert product.mesh.boundsM.min[1] == pytest.approx(0, abs=1e-9)
    assert product.mesh.boundsM.min[0] + product.mesh.boundsM.max[0] == pytest.approx(0, abs=1e-3)
    assert product.mesh.boundsM.min[2] + product.mesh.boundsM.max[2] == pytest.approx(0, abs=1e-3)
    assert product.mesh.normalization.unit == "m"
    assert product.mesh.normalization.upAxis == "+y"
    assert product.mesh.normalization.originRule == "floor-centre"


@pytest.mark.parametrize("query,expected", [
    (CatalogueQuery(room_type="bedroom"), 1), (CatalogueQuery(room_type="living-room"), 0),
    (CatalogueQuery(category="bed"), 1), (CatalogueQuery(category="sofa"), 0),
    (CatalogueQuery(style_tag="tufted"), 1), (CatalogueQuery(style_tag="brutalist"), 0),
])
def test_catalogue_queries(query, expected) -> None:
    assert len(catalogue.list(query)) == expected


def test_catalogue_returns_none_for_unknown_product() -> None:
    assert catalogue.get("no-such-product") is None


def test_catalogue_rejects_duplicate_ids(product) -> None:
    with pytest.raises(ValueError, match="Duplicate Product id"):
        StaticCatalogue((product, product))


@pytest.mark.parametrize("availability,url", [("purchasable", ""), ("unavailable", "https://example.com/product")])
def test_product_rejects_inconsistent_purchase_links(product, availability, url) -> None:
    value = as_dict(product)
    value["purchase"]["availability"] = availability
    value["purchaseUrl"] = url
    with pytest.raises(ValidationError, match="purchase"):
        Product.model_validate(value)


@pytest.mark.parametrize("dimensions", [
    {"widthM": 0, "heightM": 1, "depthM": 1},
    {"widthM": -1, "heightM": 1, "depthM": 1},
    {"widthM": "NaN", "heightM": 1, "depthM": 1},
])
def test_product_rejects_nonsense_dimensions(product, dimensions) -> None:
    value = as_dict(product)
    value["dimensionsM"] = dimensions
    with pytest.raises(ValidationError):
        Product.model_validate(value)


@pytest.mark.parametrize("levels", [[0, 1], [0, 2, 1], [0, 1, 2, 2]])
def test_product_rejects_wrong_lod_contract(product, levels) -> None:
    value = as_dict(product)
    source = value["mesh"]["lods"]
    value["mesh"]["lods"] = [source[min(level, 2)] for level in levels]
    with pytest.raises(ValidationError):
        Product.model_validate(value)


@pytest.mark.parametrize("field", ["source", "holder", "citation", "modifications"])
def test_product_rejects_blank_attribution(product, field) -> None:
    value = as_dict(product)
    value["attribution"][field] = " "
    with pytest.raises(ValidationError):
        Product.model_validate(value)


def test_product_rejects_noncanonical_front_axis(product) -> None:
    value = as_dict(product)
    value["frontAxis"] = "-z"
    with pytest.raises(ValidationError):
        Product.model_validate(value)


@pytest.mark.parametrize("axis", ["width", "height", "depth"])
def test_listing_dimensions_are_only_a_sanity_check(axis) -> None:
    evidence = {row["axis"]: row for row in dimension_evidence(FEATURED_PRODUCT_ID)}[axis]
    assert abs(float(evidence["deltaPercent"])) < 6


def test_provider_vocabulary_stops_at_the_adapter() -> None:
    root = Path(__file__).resolve().parents[1] / "api"
    adapter = root / "catalogue" / "providers" / "abo.py"
    forbidden = ("item_id", "item_name", "item_dimensions", "B07B4W5T9D", "amazon-berkeley")
    offenders = []
    for path in root.rglob("*.py"):
        if path == adapter:
            continue
        text = path.read_text(encoding="utf-8").lower()
        offenders.extend(f"{path.relative_to(root)}: {token}" for token in forbidden if token.lower() in text)
    assert offenders == []
