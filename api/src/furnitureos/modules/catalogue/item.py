"""The catalogue item: what the store sells, parsed and validated.

Two rules carry the product's whole promise, so they are enforced here rather than
trusted:

  * **Dimensions are true metres.** "It fits" in the planner has to mean "it fits" on
    delivery day, and the same numbers drive the drawn size and the collision size.
  * **Prices are whole VND integers.** Vietnamese dong has no fractional unit. A price
    that arrives with decimals is a data-entry mistake, and letting one through opens a
    float path that ends in a total that is off by a few dong for no reason.

Stock lives on the item because the columns are cheap and issue 13 may fill them in.
Nothing renders it in v1, and the wire format in schemas.py deliberately omits it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEEDS_DIR = Path(__file__).resolve().parent / "seeds"


class ItemError(ValueError):
    """A catalogue item is malformed."""


@dataclass(frozen=True)
class Item:
    """One sellable thing, at its true size and its true price.

    `preset_ref` names the 3D archetype the scene draws it as. Until issue 14 supplies
    real models every ref resolves to a correctly sized box, which is why the ref is
    required now: the seam has to be populated before there is anything to hang on it.
    """

    id: str
    name: str
    category: str
    width_m: float
    depth_m: float
    height_m: float
    price_vnd: int
    preset_ref: str
    photo_url: str | None = None
    stock_qty: int = 0
    lead_time_days: int = 0


def load_seed_items() -> list[Item]:
    """Every placeholder item, validated. Issue 13 replaces the file, not the schema."""
    raw = json.loads((SEEDS_DIR / "items.json").read_text(encoding="utf-8"))
    return [parse_item(entry) for entry in raw["items"]]


def parse_item(raw: dict[str, Any]) -> Item:
    """Parse one raw item, raising ItemError on anything a buyer must not see."""
    return Item(
        id=_required_text(raw.get("id"), "id"),
        name=_required_text(raw.get("name"), "name"),
        category=_required_text(raw.get("category"), "category"),
        width_m=_positive_metres(raw.get("width_m"), "width_m"),
        depth_m=_positive_metres(raw.get("depth_m"), "depth_m"),
        height_m=_positive_metres(raw.get("height_m"), "height_m"),
        price_vnd=_whole_dong(raw.get("price_vnd")),
        preset_ref=_required_text(raw.get("preset_ref"), "preset_ref"),
        photo_url=_optional_text(raw.get("photo_url")),
        stock_qty=_count(raw.get("stock_qty"), "stock_qty"),
        lead_time_days=_count(raw.get("lead_time_days"), "lead_time_days"),
    )


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ItemError(f"item {field} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_metres(value: Any, field: str) -> float:
    try:
        metres = float(value)
    except (TypeError, ValueError) as exc:
        raise ItemError(f"item {field} must be a number of metres") from exc
    if metres <= 0:
        raise ItemError(f"item {field} must be positive, got {metres}")
    return metres


def _whole_dong(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ItemError(f"price_vnd must be a whole number of dong, got {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ItemError(f"price_vnd must be a whole number of dong, got {value!r}")
    price = int(value)
    if price < 0:
        raise ItemError(f"price_vnd must not be negative, got {price}")
    return price


def _count(value: Any, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ItemError(f"{field} must be a whole number, got {value!r}")
    if value < 0:
        raise ItemError(f"{field} must not be negative, got {value}")
    return value
