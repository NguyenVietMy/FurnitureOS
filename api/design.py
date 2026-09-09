"""Deterministic accepted bedroom Design."""
from __future__ import annotations

from .catalogue import Catalogue, catalogue
from .domain import place_against_wall
from .models import PreviewDesign, RoomShell

FEATURED_PRODUCT_ID = "bed-prudence-tufted-queen-natural"


def bedroom_room_shell() -> RoomShell:
    return RoomShell.model_validate({
        "id": "room-bedroom-4x3",
        "floorPolygon": [[-2, -1.5], [-2, 1.5], [2, 1.5], [2, -1.5]],
        "ceilingHeightM": 2.5,
        "walls": [
            {"id": "wall-north", "label": "North wall", "start": [-2, -1.5], "end": [2, -1.5]},
            {"id": "wall-east", "label": "East wall", "start": [2, -1.5], "end": [2, 1.5]},
            {"id": "wall-south", "label": "South wall", "start": [2, 1.5], "end": [-2, 1.5]},
            {"id": "wall-west", "label": "West wall", "start": [-2, 1.5], "end": [-2, -1.5]},
        ],
    })


def bedroom_design(source: Catalogue = catalogue) -> PreviewDesign:
    product = source.get(FEATURED_PRODUCT_ID)
    if product is None:
        raise RuntimeError(f"Catalogue has no Product {FEATURED_PRODUCT_ID}")
    room = bedroom_room_shell()
    return PreviewDesign(room=room, product=product, fit=place_against_wall(product, room, "wall-north", "back"))
