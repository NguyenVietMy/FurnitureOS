"""Immutable generation policy. Geometry remains in the existing authority."""
from dataclasses import dataclass

from .models import ProductCategory, RoomType


@dataclass(frozen=True)
class RoomPolicy:
    room_type: RoomType
    version: str
    anchors: tuple[tuple[str, ProductCategory], ...]
    optional: tuple[tuple[ProductCategory, int], ...]
    request_limit: int
    spatial_repair: bool = True

    @property
    def anchor_ids(self) -> frozenset[str]:
        return frozenset(i for i, _ in self.anchors)

    @property
    def categories(self) -> frozenset[ProductCategory]:
        return frozenset(c for _, c in self.anchors) | frozenset(c for c, _ in self.optional)

    def category_limit(self, category: ProductCategory) -> int:
        return sum(c == category for _, c in self.anchors) + dict(self.optional).get(category, 0)


BEDROOM_POLICY = RoomPolicy('bedroom', 'bed-plus-optional-rug-v1', (('anchor-bed', 'bed'),), (('rug', 1),), 2)
LIVING_POLICY = RoomPolicy('living-room', 'seating-sofa-coffee-table-chair-v1', (('anchor-sofa', 'sofa'), ('anchor-table', 'table'), ('anchor-chair', 'chair')), (('chair', 1), ('rug', 1), ('lamp', 1)), 6)


def room_policy(room_type: RoomType) -> RoomPolicy:
    if room_type == 'bedroom':
        return BEDROOM_POLICY
    if room_type == 'living-room':
        return LIVING_POLICY
    raise ValueError('An explicit supported Room Type is required')
