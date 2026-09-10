"""Amazon Berkeley Objects adapter; provider vocabulary stops in this module."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.catalogue.contract import CatalogueEntry
from api.models import AccessRegion, Product, ProductCategory, ProductFace

ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = Path(__file__).with_name("abo-seed.json")
PUBLISHED_PRODUCTS_DIR = ROOT / "public" / "products"
BUNDLED_MANIFEST_DIR = Path(__file__).with_name("manifests")
ASSET_BUDGET_BYTES = 5_000_000
PositiveFinite = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Vec3 = tuple[float, float, float]
INCHES_PER_METRE = 39.37007874015748


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class ManifestBounds(ManifestModel):
    min: Vec3
    max: Vec3
    size: Vec3


class ManifestSource(ManifestModel):
    url: str
    sha256: str
    bytes: int = Field(gt=0)
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
    bounds: ManifestBounds
    appliedTransform: ManifestTransform
    note: str


class ManifestBudget(ManifestModel):
    limitBytes: int = Field(gt=0)
    totalCompressedBytes: int = Field(gt=0)
    sharedBytes: int = Field(gt=0)


class ManifestTexture(ManifestModel):
    file: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    supercompression: Literal["BasisLZ"]


class ManifestLod(ManifestModel):
    level: Literal[0, 1, 2]
    url: str
    triangles: int = Field(gt=0)
    exclusiveBytes: int = Field(gt=0)
    textureMaxPx: Literal[2048, 1024, 512]
    bounds: ManifestBounds


class AssetManifest(ManifestModel):
    productId: str
    source: ManifestSource
    normalization: ManifestNormalization
    budget: ManifestBudget
    sharedTextures: tuple[ManifestTexture, ...]
    lods: tuple[ManifestLod, ...]

    @model_validator(mode="after")
    def valid_publication(self) -> "AssetManifest":
        if self.budget.limitBytes != ASSET_BUDGET_BYTES:
            raise ValueError("asset manifest budget limit drifted")
        if self.budget.totalCompressedBytes >= self.budget.limitBytes:
            raise ValueError("Product asset total must be strictly below 5,000,000 bytes")
        if [lod.level for lod in self.lods] != [0, 1, 2]:
            raise ValueError("asset manifest must contain ordered LODs [0, 1, 2]")
        if [lod.textureMaxPx for lod in self.lods] != [2048, 1024, 512]:
            raise ValueError("asset manifest texture refinement levels drifted")
        if self.normalization.bounds.size != self.source.bounds.size:
            raise ValueError("normalization must preserve source dimensions")
        return self


class SeedStyle(StrictModel):
    id: str = Field(pattern=r"^style-\d\d$")
    privateName: str = Field(min_length=1)
    referenceImageIds: tuple[str, ...]
    referenceImageStatus: Literal["pending-owner-approval", "approved"]


class SeedStyleVocabulary(StrictModel):
    status: Literal["provisional-pending-owner-approval", "owner-approved"]
    styles: tuple[SeedStyle, ...] = Field(min_length=4, max_length=5)


class SeedProduct(StrictModel):
    productId: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    itemId: str = Field(pattern=r"^[A-Z0-9]{10}$")
    displayName: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    colour: str = Field(min_length=1)
    category: ProductCategory
    sourcePath: str = Field(pattern=r"^[A-Z0-9]/[A-Z0-9]{10}\.glb$")
    sourceSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sourceBytes: int = Field(gt=0)
    listingDimensions: "SeedListingDimensions | None" = None
    privateStyleIds: tuple[str, ...] = Field(min_length=1)
    wallContactFaces: tuple[ProductFace, ...]
    accessRegions: tuple[AccessRegion, ...]


class SeedListingDimensions(StrictModel):
    width: PositiveFinite
    height: PositiveFinite
    depth: PositiveFinite
    unit: Literal["inches"]


class SeedCatalogue(StrictModel):
    catalogueVersion: str = Field(min_length=1)
    curatedOn: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    styleVocabulary: SeedStyleVocabulary
    products: tuple[SeedProduct, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def valid_seed(self) -> "SeedCatalogue":
        product_ids = [product.productId for product in self.products]
        item_ids = [product.itemId for product in self.products]
        style_ids = [style.id for style in self.styleVocabulary.styles]
        if len(set(product_ids)) != len(product_ids) or len(set(item_ids)) != len(item_ids):
            raise ValueError("ABO seed Products and source item IDs must be unique")
        if len(set(style_ids)) != len(style_ids):
            raise ValueError("private Style IDs must be unique")
        known_styles = set(style_ids)
        for product in self.products:
            if not set(product.privateStyleIds) <= known_styles:
                raise ValueError(f"{product.productId} uses an unknown private Style ID")
            if len(set(product.privateStyleIds)) != len(product.privateStyleIds):
                raise ValueError(f"{product.productId} repeats a private Style ID")
        return self


_DATASET = {
    "name": "Amazon Berkeley Objects (ABO)",
    "holder": "Amazon.com, Inc.",
    "license": "CC BY 4.0",
    "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
    "sourceUrl": "https://amazon-berkeley-objects.s3.amazonaws.com/index.html",
    "citation": 'Collins et al., "ABO: Dataset and Benchmarks for Real-World 3D Object Understanding", CVPR 2022',
    "licenseNote": (
        "The ABO download page and archive contain CC BY 4.0 terms, while the AWS Registry "
        "and CVPR paper state CC BY-NC 4.0. Commercial rights are unresolved."
    ),
    "licenseEvidence": [
        {
            "label": "ABO dataset download page and archive licence",
            "recordedLicense": "CC BY 4.0",
            "url": "https://amazon-berkeley-objects.s3.amazonaws.com/index.html",
        },
        {
            "label": "AWS Registry of Open Data entry",
            "recordedLicense": "CC BY-NC 4.0",
            "url": "https://registry.opendata.aws/amazon-berkeley-objects/",
        },
        {
            "label": "ABO CVPR 2022 paper",
            "recordedLicense": "CC BY-NC 4.0",
            "url": "https://openaccess.thecvf.com/content/CVPR2022/html/Collins_ABO_Dataset_and_Benchmarks_for_Real-World_3D_Object_Understanding_CVPR_2022_paper.html",
        },
    ],
}


@lru_cache
def seed_catalogue() -> SeedCatalogue:
    return SeedCatalogue.model_validate_json(SEED_PATH.read_text(encoding="utf-8"))


def catalogue_version() -> str:
    return seed_catalogue().catalogueVersion


def dimension_evidence(product_id: str) -> tuple[dict[str, float | str], ...]:
    """Compare measured Mesh axes with independent listing text when recorded."""
    record = next((item for item in seed_catalogue().products if item.productId == product_id), None)
    if record is None:
        raise ValueError(f'No ABO entry for "{product_id}"')
    if record.listingDimensions is None:
        raise ValueError(f'No independent listing dimensions recorded for "{product_id}"')
    product = _to_entry(record).product
    values = (
        ("width", product.dimensionsM.widthM, record.listingDimensions.width),
        ("height", product.dimensionsM.heightM, record.listingDimensions.height),
        ("depth", product.dimensionsM.depthM, record.listingDimensions.depth),
    )
    return tuple({
        "axis": axis,
        "measuredM": measured,
        "listedM": inches / INCHES_PER_METRE,
        "listedText": f"{inches:g} inches",
        "deltaPercent": (measured - inches / INCHES_PER_METRE) / (inches / INCHES_PER_METRE) * 100,
    } for axis, measured, inches in values)


@lru_cache
def asset_manifest(product_id: str) -> AssetManifest:
    published = PUBLISHED_PRODUCTS_DIR / product_id / "asset-manifest.json"
    bundled = BUNDLED_MANIFEST_DIR / f"{product_id}.json"
    path = published if published.is_file() else bundled
    manifest = AssetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.productId != product_id:
        raise ValueError("asset manifest Product id does not match its publication directory")
    return manifest


def _to_entry(record: SeedProduct) -> CatalogueEntry:
    manifest = asset_manifest(record.productId)
    expected_url = (
        "https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/"
        f"{record.sourcePath}"
    )
    if manifest.source.url != expected_url:
        raise ValueError(f"{record.productId} source URL drifted from the curated record")
    if manifest.source.sha256 != record.sourceSha256 or manifest.source.bytes != record.sourceBytes:
        raise ValueError(f"{record.productId} source hash or byte count drifted")

    width, height, depth = manifest.normalization.bounds.size
    product = Product.model_validate({
        "id": record.productId,
        "displayName": record.displayName,
        "brand": record.brand,
        "colour": record.colour,
        "category": record.category,
        "roomTypes": ["bedroom"],
        "dimensionsM": {"widthM": width, "heightM": height, "depthM": depth},
        "frontAxis": manifest.normalization.frontAxis,
        "wallContactFaces": record.wallContactFaces,
        "placementClass": "floor-standing",
        "accessRegions": [region.model_dump() for region in record.accessRegions],
        "mesh": {
            "lods": [
                lod.model_dump(include={"level", "url", "triangles", "exclusiveBytes"})
                for lod in manifest.lods
            ],
            "sharedTextureUrls": [
                f"/products/{record.productId}/{texture.file}"
                for texture in manifest.sharedTextures
            ],
            "normalization": {
                "unit": manifest.normalization.unit,
                "upAxis": manifest.normalization.upAxis,
                "frontAxis": manifest.normalization.frontAxis,
                "originRule": manifest.normalization.originRule,
                "transform": manifest.normalization.appliedTransform.model_dump(),
                "note": manifest.normalization.note,
            },
            "boundsM": {
                "min": manifest.normalization.bounds.min,
                "max": manifest.normalization.bounds.max,
            },
            "totalCompressedBytes": manifest.budget.totalCompressedBytes,
        },
        "purchaseUrl": "",
        "purchase": {
            "availability": "unknown",
            "checkedOn": seed_catalogue().curatedOn,
            "note": "Purchase availability was not verified; the dataset listing is provenance only.",
        },
        "attribution": {
            "source": _DATASET["name"],
            "holder": _DATASET["holder"],
            "license": _DATASET["license"],
            "licenseUrl": _DATASET["licenseUrl"],
            "sourceUrl": _DATASET["sourceUrl"],
            "materialUrl": manifest.source.url,
            "citation": _DATASET["citation"],
            "modifications": (
                "Geometry normalized to a measured floor-centre origin, simplified into three "
                "levels of detail and compressed with EXT_meshopt_compression; textures transcoded "
                "to progressive KTX2/BasisU levels capped at 2048 px. Scale and orientation preserved."
            ),
            "licenseStatus": "conflicting-source-records",
            "licenseNote": _DATASET["licenseNote"],
            "licenseEvidence": _DATASET["licenseEvidence"],
        },
    })
    return CatalogueEntry(product=product, private_style_ids=record.privateStyleIds)


@lru_cache
def abo_entries() -> tuple[CatalogueEntry, ...]:
    return tuple(_to_entry(record) for record in seed_catalogue().products)
