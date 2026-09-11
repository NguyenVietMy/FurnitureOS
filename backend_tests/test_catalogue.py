from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.catalogue import CatalogueEntry, CatalogueQuery, StaticCatalogue, catalogue, dimension_evidence
from api.catalogue.providers.abo import ASSET_BUDGET_BYTES, asset_manifest, seed_catalogue
from api.design import FEATURED_PRODUCT_ID
from api.models import Attribution, Product


def as_dict(product: Product) -> dict:
    return deepcopy(product.model_dump(mode="json"))


def test_catalogue_has_exactly_twenty_distinct_real_products() -> None:
    products = catalogue.list()
    assert len(products) == 20
    assert len({product.id for product in products}) == 20
    assert len({product.attribution.materialUrl for product in products}) == 20
    assert Counter(product.category for product in products) == {
        "bed": 4, "nightstand": 4, "wardrobe": 2, "dresser": 2,
        "chair": 3, "rug": 3, "lamp": 2,
    }


def test_catalogue_version_and_provisional_style_vocabulary_are_private() -> None:
    seed = seed_catalogue()
    assert catalogue.version == seed.catalogueVersion
    assert seed.styleVocabulary.status == "provisional-pending-owner-approval"
    assert len(seed.styleVocabulary.styles) == 5
    assert all(style.referenceImageStatus == "pending-owner-approval" for style in seed.styleVocabulary.styles)
    assert all(not style.referenceImageIds for style in seed.styleVocabulary.styles)
    public_json = "".join(product.model_dump_json() for product in catalogue.list())
    assert "privateStyle" not in public_json
    assert all(style.privateName not in public_json for style in seed.styleVocabulary.styles)


def test_curated_source_identity_and_manifest_are_pinned() -> None:
    for record in seed_catalogue().products:
        manifest = asset_manifest(record.productId)
        assert manifest.productId == record.productId
        assert manifest.source.sha256 == record.sourceSha256
        assert manifest.source.bytes == record.sourceBytes
        assert manifest.source.url.endswith(record.sourcePath)
        assert manifest.budget.limitBytes == ASSET_BUDGET_BYTES == 5_000_000
        assert manifest.budget.totalCompressedBytes < ASSET_BUDGET_BYTES


def test_manifest_is_the_dimensional_source_of_truth() -> None:
    for product in catalogue.list():
        manifest = asset_manifest(product.id)
        assert tuple(product.dimensionsM.model_dump().values()) == manifest.normalization.bounds.size
        assert product.mesh.normalization.frontAxis == manifest.normalization.frontAxis
        assert product.mesh.normalization.transform.translation == manifest.normalization.appliedTransform.translation


@pytest.mark.parametrize("axis,expected", [("widthM", 1.695826), ("heightM", 1.425926), ("depthM", 2.23299)])
def test_featured_dimensions_retain_independent_exact_values(product, axis, expected) -> None:
    assert getattr(product.dimensionsM, axis) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("field,index", [("widthM", 0), ("heightM", 1), ("depthM", 2)])
def test_each_dimension_axis_matches_the_measured_manifest(field, index) -> None:
    for product in catalogue.list():
        assert getattr(product.dimensionsM, field) == pytest.approx(
            asset_manifest(product.id).normalization.bounds.size[index], abs=1e-6,
        )


def test_all_meshes_are_floor_centred_and_normalized() -> None:
    for product in catalogue.list():
        assert product.frontAxis == "+z"
        assert product.mesh.boundsM.min[1] == pytest.approx(0, abs=1e-9)
        assert product.mesh.boundsM.min[0] + product.mesh.boundsM.max[0] == pytest.approx(0, abs=1e-3)
        assert product.mesh.boundsM.min[2] + product.mesh.boundsM.max[2] == pytest.approx(0, abs=1e-3)
        assert product.mesh.normalization.unit == "m"
        assert product.mesh.normalization.upAxis == "+y"
        assert product.mesh.normalization.originRule == "floor-centre"


def test_all_products_disclose_purchase_and_licence_uncertainty() -> None:
    for product in catalogue.list():
        assert product.purchaseUrl == ""
        assert product.purchase.availability == "unknown"
        assert "not verified" in product.purchase.note.lower()
        assert product.attribution.licenseStatus == "conflicting-source-records"
        recorded = {evidence.recordedLicense for evidence in product.attribution.licenseEvidence}
        assert recorded == {"CC BY 4.0", "CC BY-NC 4.0"}
        assert "unresolved" in product.attribution.licenseNote.lower()


def test_provider_neutral_attribution_accepts_one_evidenced_verified_license() -> None:
    attribution = Attribution.model_validate({
        "source": "Synthetic provider catalogue",
        "holder": "Example Rights Holder",
        "license": "CC BY 4.0",
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "sourceUrl": "https://example.com/catalogue",
        "materialUrl": "https://example.com/models/chair.glb",
        "citation": "Example provider record",
        "modifications": "Normalized and compressed for FurnitureOS.",
        "licenseStatus": "verified",
        "licenseNote": "The provider publishes one unambiguous license record.",
        "licenseEvidence": [{
            "label": "Provider license page",
            "recordedLicense": "CC BY 4.0",
            "url": "https://example.com/license",
        }],
    })
    assert attribution.licenseStatus == "verified"
    assert len(attribution.licenseEvidence) == 1


@pytest.mark.parametrize(
    "status,evidence",
    [
        ("verified", []),
        ("conflicting-source-records", [{
            "label": "Only record",
            "recordedLicense": "CC BY 4.0",
            "url": "https://example.com/license",
        }]),
        ("conflicting-source-records", [
            {
                "label": "First record",
                "recordedLicense": "CC BY 4.0",
                "url": "https://example.com/license-a",
            },
            {
                "label": "Duplicate conclusion",
                "recordedLicense": "CC BY 4.0",
                "url": "https://example.com/license-b",
            },
        ]),
    ],
)
def test_attribution_rejects_status_without_required_evidence(product, status, evidence) -> None:
    value = as_dict(product)["attribution"]
    value["licenseStatus"] = status
    value["licenseEvidence"] = evidence
    with pytest.raises(ValidationError, match="license"):
        Attribution.model_validate(value)


def test_unknown_license_status_can_truthfully_have_no_evidence(product) -> None:
    value = as_dict(product)["attribution"]
    value["licenseStatus"] = "unknown"
    value["licenseEvidence"] = []
    value["licenseNote"] = "No authoritative license evidence is currently available."
    assert Attribution.model_validate(value).licenseEvidence == ()


def test_featured_purchase_disclosure_retains_date_and_unknown_status(product) -> None:
    assert product.purchaseUrl == ""
    assert product.purchase.availability == "unknown"
    assert product.purchase.checkedOn.isoformat() == seed_catalogue().curatedOn
    assert "not verified" in product.purchase.note.lower()


@pytest.mark.parametrize(
    "field",
    ["source", "holder", "license", "licenseUrl", "sourceUrl", "materialUrl", "citation", "modifications"],
)
def test_attribution_fields_are_nonblank_for_every_product(field) -> None:
    assert all(str(getattr(product.attribution, field)).strip() for product in catalogue.list())


def test_attribution_links_collection_and_exact_material_for_every_product() -> None:
    for product in catalogue.list():
        assert product.attribution.sourceUrl.startswith("https://")
        assert product.attribution.materialUrl == asset_manifest(product.id).source.url
        assert product.attribution.materialUrl.endswith(".glb")


@pytest.mark.parametrize("field", ["source", "holder", "citation", "modifications"])
def test_product_rejects_blank_attribution(product, field) -> None:
    value = as_dict(product)
    value["attribution"][field] = " "
    with pytest.raises(ValidationError):
        Product.model_validate(value)


def test_every_curated_product_publishes_its_provider_neutral_placement_class() -> None:
    for product in catalogue.list():
        assert product.roomTypes == ("bedroom",)
        expected = "floor-covering" if product.category == "rug" else "floor-standing"
        assert product.placementClass == expected


def test_rug_and_lamp_seed_records_declare_placement_class_explicitly() -> None:
    records = [record for record in seed_catalogue().products if record.category in {"rug", "lamp"}]

    assert len(records) == 5
    assert all("placementClass" in record.model_fields_set for record in records)
    assert [record.placementClass for record in records if record.category == "rug"] == ["floor-covering"] * 3
    assert [record.placementClass for record in records if record.category == "lamp"] == ["floor-standing"] * 2


def test_wall_contact_metadata_matches_product_use() -> None:
    wall_categories = {"bed", "nightstand", "wardrobe", "dresser"}
    for product in catalogue.list():
        expected = (
            ("back", "left", "right")
            if product.id == "nightstand-alkove-hayes-wild-oak"
            else ("back",) if product.category in wall_categories else ()
        )
        assert product.wallContactFaces == expected


def test_corner_nightstand_side_contacts_preserve_access_and_publication_contract() -> None:
    product = catalogue.get("nightstand-alkove-hayes-wild-oak")

    assert product is not None
    assert product.wallContactFaces == ("back", "left", "right")
    assert [(region.face, region.required, region.purpose) for region in product.accessRegions] == [
        ("front", True, "opening the drawer"),
    ]
    assert product.mesh.boundsM.min == pytest.approx((-0.279908031, 0.0, -0.219964027))
    assert product.mesh.boundsM.max == pytest.approx((0.279908, 0.4699, 0.219964))


def test_access_metadata_is_explicit_where_operation_needs_it() -> None:
    for product in catalogue.list():
        if product.category == "rug":
            assert product.accessRegions == ()
        else:
            assert product.accessRegions
            assert all(region.depthM > 0 and region.purpose.strip() for region in product.accessRegions)


@pytest.mark.parametrize("axis", ["width", "height", "depth"])
def test_listing_dimensions_remain_an_independent_sanity_check(axis) -> None:
    evidence = {row["axis"]: row for row in dimension_evidence(FEATURED_PRODUCT_ID)}[axis]
    assert evidence["listedText"].endswith("inches")
    assert abs(float(evidence["deltaPercent"])) < 6


def test_every_mesh_has_decreasing_three_level_lods() -> None:
    for product in catalogue.list():
        assert [lod.level for lod in product.mesh.lods] == [0, 1, 2]
        assert [lod.triangles for lod in product.mesh.lods] == sorted(
            (lod.triangles for lod in product.mesh.lods), reverse=True,
        )
        assert [lod.exclusiveBytes for lod in product.mesh.lods] == sorted(
            (lod.exclusiveBytes for lod in product.mesh.lods), reverse=True,
        )


@pytest.mark.parametrize("query,expected", [
    (CatalogueQuery(room_type="bedroom"), 20),
    (CatalogueQuery(room_type="living-room"), 0),
    (CatalogueQuery(category="bed"), 4),
    (CatalogueQuery(category="sofa"), 0),
    (CatalogueQuery(private_style_id="style-01"), 14),
    (CatalogueQuery(private_style_id="style-99"), 0),
])
def test_catalogue_queries(query, expected) -> None:
    assert len(catalogue.list(query)) == expected


def test_catalogue_returns_none_for_unknown_product() -> None:
    assert catalogue.get("no-such-product") is None
    assert catalogue.private_style_ids("no-such-product") == ()


def test_catalogue_rejects_duplicate_ids(product) -> None:
    entry = CatalogueEntry(product=product, private_style_ids=("style-01",))
    with pytest.raises(ValueError, match="Duplicate Product id"):
        StaticCatalogue("test-version", (entry, entry))


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


def test_product_rejects_noncanonical_front_axis(product) -> None:
    value = as_dict(product)
    value["frontAxis"] = "-z"
    with pytest.raises(ValidationError):
        Product.model_validate(value)


def test_provider_vocabulary_stops_at_the_adapter() -> None:
    root = Path(__file__).resolve().parents[1] / "api"
    adapter_files = {
        root / "catalogue" / "providers" / "abo.py",
        root / "catalogue" / "providers" / "abo-seed.json",
    }
    forbidden = ("item_id", "item_name", "item_dimensions", "B07B4W5T9D", "amazon-berkeley")
    offenders = []
    for path in root.rglob("*"):
        if (
            path in adapter_files
            or "manifests" in path.parts
            or not path.is_file()
            or path.suffix not in {".py", ".json"}
        ):
            continue
        text = path.read_text(encoding="utf-8").lower()
        offenders.extend(f"{path.relative_to(root)}: {token}" for token in forbidden if token.lower() in text)
    assert offenders == []


def test_featured_product_preserves_the_room_preview_contract(product) -> None:
    assert product.id == FEATURED_PRODUCT_ID
    assert product.category == "bed"
    assert product.wallContactFaces == ("back",)
    assert sorted(region.face for region in product.accessRegions) == ["front", "left", "right"]
    assert product.frontAxis == "+z"
