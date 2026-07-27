"""Wire format for unit plans.

Kept separate from the domain model in plan.py so the HTTP contract can be changed
without touching geometry, and so derived values (area, bedrooms, wall lengths) are
computed server-side and simply read by the client.

Two projections of the same plan: `UnitSummaryOut` for a gallery card and `UnitOut` for
the renderer. Both read the derived values off `UnitPlan`, so a card can never
contradict the page it opens.
"""

from pydantic import BaseModel

from furnitureos.modules.units.plan import UnitPlan

# Areas are metres squared derived from traced coordinates. Three decimals is a square
# millimetre — already past any precision a floorplan carries, but it keeps the two
# projections byte-identical rather than merely close.
AREA_DECIMALS = 3


class WallOut(BaseModel):
    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    thickness_m: float
    length_m: float


class OpeningOut(BaseModel):
    wall: str
    kind: str
    offset_m: float
    width_m: float
    sill_m: float
    head_m: float


class RoomOut(BaseModel):
    key: str
    name: str
    type: str
    polygon: list[tuple[float, float]]


class UnitSummaryOut(BaseModel):
    """A gallery card: what it displays, plus the polygons it draws a thumbnail from.

    No walls and no openings. The gallery lists the whole catalogue of layouts at once,
    and every wall it shipped would be one nobody looks at until they click through.
    """

    slug: str
    name: str
    building: str
    area_m2: float
    bedrooms: int
    outline: list[tuple[float, float]]
    rooms: list[RoomOut]

    @classmethod
    def from_plan(cls, plan: UnitPlan) -> "UnitSummaryOut":
        return cls(
            slug=plan.slug,
            name=plan.name,
            building=plan.building,
            area_m2=round(plan.area_m2, AREA_DECIMALS),
            bedrooms=plan.bedrooms,
            outline=plan.outline,
            rooms=[
                RoomOut(key=room.key, name=room.name, type=room.type, polygon=room.polygon)
                for room in plan.rooms
            ],
        )


class UnitOut(BaseModel):
    slug: str
    name: str
    building: str
    ceiling_height_m: float
    area_m2: float
    bedrooms: int
    outline: list[tuple[float, float]]
    walls: list[WallOut]
    rooms: list[RoomOut]
    openings: list[OpeningOut]

    @classmethod
    def from_plan(cls, plan: UnitPlan) -> "UnitOut":
        return cls(
            slug=plan.slug,
            name=plan.name,
            building=plan.building,
            ceiling_height_m=plan.ceiling_height_m,
            area_m2=round(plan.area_m2, AREA_DECIMALS),
            bedrooms=plan.bedrooms,
            outline=plan.outline,
            walls=[
                WallOut(
                    id=wall.id,
                    start=wall.start,
                    end=wall.end,
                    thickness_m=wall.thickness_m,
                    length_m=round(wall.length_m, 6),
                )
                for wall in plan.walls
            ],
            rooms=[
                RoomOut(key=room.key, name=room.name, type=room.type, polygon=room.polygon)
                for room in plan.rooms
            ],
            openings=[
                OpeningOut(
                    wall=opening.wall,
                    kind=opening.kind,
                    offset_m=opening.offset_m,
                    width_m=opening.width_m,
                    sill_m=opening.sill_m,
                    head_m=opening.head_m,
                )
                for opening in plan.openings
            ],
        )
