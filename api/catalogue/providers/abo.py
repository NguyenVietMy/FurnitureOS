"""Amazon Berkeley Objects adapter; provider vocabulary stops in this module."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.models import Product

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ID = "bed-prudence-tufted-queen-natural"
PUBLISHED_MANIFEST_PATH = ROOT / "public" / "products" / PRODUCT_ID / "asset-manifest.json"
BUNDLED_MANIFEST_PATH = Path(__file__).with_name("asset-manifest.json")
PositiveFinite = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Vec3 = tuple[float, float, float]
INCHES_PER_METRE = 39.3700787


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ManifestBounds(ManifestModel):
    min: Vec3
    max: Vec3
    size: Vec3


class ManifestSource(ManifestModel):
    url: str
    bounds: ManifestBounds


class ManifestTransform(ManifestModel):
    translation: Vec3
    rotationYaw: float
    scale: PositiveFinite


class ManifestNormalization(ManifestModel):
    unit: Literal["m"]
    upAxis: Literal["+y"]
    frontAxis: Literal["+z"]
    originRule: Literal["floor-centre"]
    appliedTransform: ManifestTransform
    note: str


class ManifestBudget(ManifestModel):
    totalCompressedBytes: int = Field(gt=0)


class ManifestTexture(ManifestModel):
    file: str


class ManifestLod(ManifestModel):
    level: Literal[0, 1, 2]
    url: str
    triangles: int = Field(gt=0)
    exclusiveBytes: int = Field(gt=0)


class AssetManifest(ManifestModel):
    productId: str
    source: ManifestSource
    normalization: ManifestNormalization
    budget: ManifestBudget
    sharedTextures: tuple[ManifestTexture, ...]
    lods: tuple[ManifestLod, ...]


def asset_manifest() -> AssetManifest:
    manifest_path = PUBLISHED_MANIFEST_PATH if PUBLISHED_MANIFEST_PATH.is_file() else BUNDLED_MANIFEST_PATH
    manifest = AssetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.productId != PRODUCT_ID:
        raise ValueError("asset manifest Product id does not match its publication directory")
    return manifest


# Source record in provider terms. Nothing outside this adapter reads these keys.
_LISTING = {
    "item_id": "B07B4W5T9D",
    "item_name": "Prudence Tufted Queen Bed",
    "brand": "Stone & Beam",
    "color": "Spinnsol Natural",
    "item_dimensions": {"length": 66, "height": 56, "width": 92},
    "domain_name": "amazon.com",
}

_DATASET = {
    "name": "Amazon Berkeley Objects (ABO)",
    "holder": "Amazon.com, Inc.",
    "license": "CC BY 4.0",
    "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
    "sourceUrl": "https://amazon-berkeley-objects.s3.amazonaws.com/index.html",
    "citation": 'Collins et al., "ABO: Dataset and Benchmarks for Real-World 3D Object Understanding", CVPR 2022',
}


def _to_product() -> Product:
    manifest = asset_manifest()
    width, height, depth = manifest.source.bounds.size
    return Product.model_validate({
        "id": PRODUCT_ID,
        "displayName": _LISTING["item_name"],
        "brand": _LISTING["brand"],
        "colour": _LISTING["color"],
        "category": "bed",
        "roomTypes": ["bedroom"],
        "styleTags": ["transitional", "upholstered", "tufted", "neutral", "queen"],
        "dimensionsM": {"widthM": width, "heightM": height, "depthM": depth},
        "frontAxis": manifest.normalization.frontAxis,
        "wallContactFaces": ["back"],
        "placementClass": "floor-standing",
        "accessRegions": [
            {"face": "left", "depthM": 0.6, "required": True, "purpose": "getting in and out"},
            {"face": "right", "depthM": 0.6, "required": True, "purpose": "getting in and out"},
            {"face": "front", "depthM": 0.6, "required": True, "purpose": "walking past the foot"},
        ],
        "mesh": {
            "lods": [lod.model_dump() for lod in manifest.lods],
            "sharedTextureUrls": [f"/products/{PRODUCT_ID}/{texture.file}" for texture in manifest.sharedTextures],
            "normalization": {
                "unit": manifest.normalization.unit,
                "upAxis": manifest.normalization.upAxis,
                "frontAxis": manifest.normalization.frontAxis,
                "originRule": manifest.normalization.originRule,
                "transform": manifest.normalization.appliedTransform.model_dump(),
                "note": manifest.normalization.note,
            },
            "boundsM": {"min": manifest.source.bounds.min, "max": manifest.source.bounds.max},
            "totalCompressedBytes": manifest.budget.totalCompressedBytes,
        },
        "purchaseUrl": "",
        "purchase": {
            "availability": "unavailable",
            "checkedOn": "2026-09-08",
            "note": "Currently unavailable at the checked marketplace listing.",
        },
        "attribution": {
            "source": _DATASET["name"],
            "holder": _DATASET["holder"],
            "license": _DATASET["license"],
            "licenseUrl": _DATASET["licenseUrl"],
            "sourceUrl": _DATASET["sourceUrl"],
            "materialUrl": manifest.source.url,
            "citation": _DATASET["citation"],
            "modifications": "Geometry simplified into three levels of detail and compressed with EXT_meshopt_compression; textures transcoded to KTX2/BasisU at 2048 px. No change to scale, orientation or origin.",
        },
    })


def abo_products() -> tuple[Product, ...]:
    return (_to_product(),)


def dimension_evidence(product_id: str) -> tuple[dict[str, float | str], ...]:
    if product_id != PRODUCT_ID:
        raise ValueError(f'No ABO entry for "{product_id}"')
    product = _to_product()
    listed = _LISTING["item_dimensions"]
    values = (
        ("width", product.dimensionsM.widthM, listed["length"]),
        ("height", product.dimensionsM.heightM, listed["height"]),
        ("depth", product.dimensionsM.depthM, listed["width"]),
    )
    return tuple({
        "axis": axis,
        "measuredM": measured,
        "listedM": inches / INCHES_PER_METRE,
        "listedText": f"{inches} inches",
        "deltaPercent": (measured - inches / INCHES_PER_METRE) / (inches / INCHES_PER_METRE) * 100,
    } for axis, measured, inches in values)
