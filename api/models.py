"""Validated HTTP and domain contracts for FurnitureOS."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]
PositiveFinite = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Vec2 = tuple[Finite, Finite]
Vec3 = tuple[Finite, Finite, Finite]
ProductFace = Literal["front", "back", "left", "right"]
PlacementClass = Literal["floor-standing", "wall-mounted", "ceiling-hung", "surface-standing"]
ProductCategory = Literal["bed", "nightstand", "wardrobe", "dresser", "chair", "sofa", "table", "rug", "lamp"]
RoomType = Literal["bedroom", "living-room"]
LicenseStatus = Annotated[
    Literal["verified", "unknown", "conflicting-source-records"],
    Field(description="verified has evidence; unknown has none; conflicting-source-records has divergent evidence"),
]
InvalidFitReason = Literal[
    "product-exceeds-room-bounds", "footprint-outside-room", "access-region-outside-room",
    "wall-contact-face-not-allowed", "not-touching-declared-wall", "wall-shorter-than-product",
    "exceeds-ceiling-height", "placement-class-cannot-stand-on-floor", "not-resting-on-floor",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Dimensions(ContractModel):
    widthM: PositiveFinite
    heightM: PositiveFinite
    depthM: PositiveFinite


class AccessRegion(ContractModel):
    face: ProductFace
    depthM: PositiveFinite
    required: bool
    purpose: str = Field(min_length=1)


class MeshLod(ContractModel):
    level: Literal[0, 1, 2]
    url: str = Field(pattern=r"^/")
    triangles: int = Field(gt=0)
    exclusiveBytes: int = Field(gt=0)


class MeshTransform(ContractModel):
    translation: Vec3
    rotationYaw: Finite
    scale: PositiveFinite


class MeshNormalization(ContractModel):
    unit: Literal["m"]
    upAxis: Literal["+y"]
    frontAxis: Literal["+z"]
    originRule: Literal["floor-centre"]
    transform: MeshTransform
    note: str = Field(min_length=1)


class MeshBounds(ContractModel):
    min: Vec3
    max: Vec3

    @model_validator(mode="after")
    def ordered(self) -> "MeshBounds":
        if any(high < low for low, high in zip(self.min, self.max, strict=True)):
            raise ValueError("Mesh bounds max must be greater than or equal to min on every axis")
        return self


class MeshRef(ContractModel):
    lods: tuple[MeshLod, ...]
    sharedTextureUrls: tuple[str, ...] = Field(min_length=1)
    normalization: MeshNormalization
    boundsM: MeshBounds
    totalCompressedBytes: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_lods(self) -> "MeshRef":
        if [lod.level for lod in self.lods] != [0, 1, 2]:
            raise ValueError("a Product must ship exactly three LODs ordered [0, 1, 2]")
        triangles = [lod.triangles for lod in self.lods]
        sizes = [lod.exclusiveBytes for lod in self.lods]
        if not (triangles[0] > triangles[1] > triangles[2]):
            raise ValueError("LOD triangle counts must decrease from level 0 to level 2")
        if not (sizes[0] > sizes[1] > sizes[2]):
            raise ValueError("LOD exclusive byte counts must decrease from level 0 to level 2")
        if any(not url.endswith(".ktx2") for url in self.sharedTextureUrls):
            raise ValueError("all shared Product textures must be KTX2")
        return self


class PurchaseDisclosure(ContractModel):
    availability: Literal["purchasable", "unavailable", "unknown"]
    checkedOn: date
    note: str = Field(min_length=1)


class LicenseEvidence(ContractModel):
    label: str = Field(min_length=1)
    recordedLicense: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")


class Attribution(ContractModel):
    source: str = Field(min_length=1)
    holder: str = Field(min_length=1)
    license: str = Field(min_length=1)
    licenseUrl: str = Field(pattern=r"^https://")
    sourceUrl: str = Field(pattern=r"^https://")
    materialUrl: str = Field(pattern=r"^https://")
    citation: str = Field(min_length=1)
    modifications: str = Field(min_length=1)
    licenseStatus: LicenseStatus
    licenseNote: str = Field(min_length=1)
    licenseEvidence: tuple[LicenseEvidence, ...]

    @model_validator(mode="after")
    def no_blank_attribution(self) -> "Attribution":
        for name, value in self:
            if not str(value).strip():
                raise ValueError(f"empty attribution: {name}")
        if self.licenseStatus == "verified" and not self.licenseEvidence:
            raise ValueError("verified license status requires at least one evidence record")
        if self.licenseStatus == "conflicting-source-records":
            recorded = {evidence.recordedLicense.strip() for evidence in self.licenseEvidence}
            if len(self.licenseEvidence) < 2 or len(recorded) < 2:
                raise ValueError(
                    "conflicting-source-records status requires at least two evidence records "
                    "that record different licenses"
                )
        return self


class Product(ContractModel):
    id: str = Field(min_length=1)
    displayName: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    colour: str = Field(min_length=1)
    category: ProductCategory
    roomTypes: tuple[RoomType, ...] = Field(min_length=1)
    dimensionsM: Dimensions
    frontAxis: Literal["+z"]
    wallContactFaces: tuple[ProductFace, ...]
    placementClass: PlacementClass
    accessRegions: tuple[AccessRegion, ...]
    mesh: MeshRef
    purchaseUrl: str
    purchase: PurchaseDisclosure
    attribution: Attribution

    @model_validator(mode="after")
    def valid_product_contract(self) -> "Product":
        if self.frontAxis != self.mesh.normalization.frontAxis:
            raise ValueError("Product frontAxis and Mesh normalization frontAxis disagree")
        if self.purchase.availability == "purchasable" and not self.purchaseUrl.startswith("https://"):
            raise ValueError("a purchasable Product must carry an HTTPS purchase URL")
        if self.purchase.availability != "purchasable" and self.purchaseUrl:
            raise ValueError("an unavailable or unknown Product must not claim a purchase URL")
        return self


class WallSegment(ContractModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    start: Vec2
    end: Vec2

    @model_validator(mode="after")
    def nonzero(self) -> "WallSegment":
        if self.start == self.end:
            raise ValueError("a wall segment cannot have zero length")
        return self


def _edge_key(a: Vec2, b: Vec2) -> frozenset[Vec2]:
    return frozenset((a, b))


def _orientation(a: Vec2, b: Vec2, c: Vec2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(a: Vec2, b: Vec2, point: Vec2) -> bool:
    epsilon = 1e-12
    return (
        abs(_orientation(a, b, point)) <= epsilon
        and min(a[0], b[0]) - epsilon <= point[0] <= max(a[0], b[0]) + epsilon
        and min(a[1], b[1]) - epsilon <= point[1] <= max(a[1], b[1]) + epsilon
    )


def _segments_intersect(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool:
    ab_c, ab_d = _orientation(a, b, c), _orientation(a, b, d)
    cd_a, cd_b = _orientation(c, d, a), _orientation(c, d, b)
    if ((ab_c > 0 > ab_d) or (ab_d > 0 > ab_c)) and ((cd_a > 0 > cd_b) or (cd_b > 0 > cd_a)):
        return True
    return any((
        abs(ab_c) <= 1e-12 and _point_on_segment(a, b, c),
        abs(ab_d) <= 1e-12 and _point_on_segment(a, b, d),
        abs(cd_a) <= 1e-12 and _point_on_segment(c, d, a),
        abs(cd_b) <= 1e-12 and _point_on_segment(c, d, b),
    ))


def _is_simple_polygon(points: tuple[Vec2, ...]) -> bool:
    edge_count = len(points)
    for first in range(edge_count):
        first_end = (first + 1) % edge_count
        for second in range(first + 1, edge_count):
            second_end = (second + 1) % edge_count
            if first_end == second or second_end == first:
                continue
            if _segments_intersect(points[first], points[first_end], points[second], points[second_end]):
                return False
    return True


class RoomShell(ContractModel):
    id: str = Field(min_length=1)
    floorPolygon: tuple[Vec2, ...] = Field(min_length=3)
    walls: tuple[WallSegment, ...] = Field(min_length=3)
    ceilingHeightM: PositiveFinite

    @model_validator(mode="after")
    def valid_convex_shell(self) -> "RoomShell":
        if len(set(self.floorPolygon)) != len(self.floorPolygon):
            raise ValueError("Room Shell floorPolygon vertices must be unique")
        if len({wall.id for wall in self.walls}) != len(self.walls):
            raise ValueError("Room Shell wall IDs must be unique and stable")
        if not _is_simple_polygon(self.floorPolygon):
            raise ValueError("Room Shell floorPolygon must be simple and non-self-intersecting")
        signs: list[float] = []
        points = self.floorPolygon
        for index, current in enumerate(points):
            following = points[(index + 1) % len(points)]
            after = points[(index + 2) % len(points)]
            cross = (following[0] - current[0]) * (after[1] - following[1]) - (following[1] - current[1]) * (after[0] - following[0])
            if abs(cross) <= 1e-12:
                raise ValueError("Room Shell floorPolygon cannot contain collinear adjacent edges")
            signs.append(cross)
        if any(value * signs[0] < 0 for value in signs[1:]):
            raise ValueError("Room Shell floorPolygon must be convex")
        polygon_edges = {_edge_key(point, points[(index + 1) % len(points)]) for index, point in enumerate(points)}
        wall_edges = {_edge_key(wall.start, wall.end) for wall in self.walls}
        if len(self.walls) != len(points) or wall_edges != polygon_edges:
            raise ValueError("Room Shell walls must cover every floorPolygon edge exactly once")
        return self


class WallContact(ContractModel):
    wallId: str = Field(min_length=1)
    face: ProductFace


class Placement(ContractModel):
    productId: str = Field(min_length=1)
    position: Vec3
    yaw: Finite
    wallContact: WallContact | None = None


class Footprint(ContractModel):
    centre: Vec2
    yaw: Finite
    widthM: Finite = Field(ge=0)
    depthM: Finite = Field(ge=0)
    corners: tuple[Vec2, Vec2, Vec2, Vec2]


class FitMeasurements(ContractModel):
    footprint: Footprint
    clearanceM: Finite
    wallGapM: Finite | None
    heightM: PositiveFinite
    floorGapM: Finite
    topM: Finite


class FitSuccess(ContractModel):
    status: Literal["fits"]
    placement: Placement
    measurements: FitMeasurements


class InvalidFit(ContractModel):
    status: Literal["invalid-fit"]
    reason: InvalidFitReason
    detail: str = Field(min_length=1)
    productId: str = Field(min_length=1)
    roomId: str = Field(min_length=1)
    measurements: FitMeasurements


FitResultValue = Annotated[FitSuccess | InvalidFit, Field(discriminator="status")]


class FitResult(RootModel[FitResultValue]):
    pass


class PreviewDesign(ContractModel):
    room: RoomShell
    product: Product
    fit: FitResultValue


class CatalogueGallery(ContractModel):
    catalogueVersion: str = Field(min_length=1)
    products: tuple[Product, ...] = Field(min_length=1)


class PlacementValidationRequest(ContractModel):
    product: Product
    room: RoomShell
    placement: Placement


class Health(ContractModel):
    status: Literal["ok"]
