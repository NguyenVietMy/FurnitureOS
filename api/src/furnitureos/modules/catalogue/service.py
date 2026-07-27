"""Reading and seeding catalogue items.

Rows are mapped back through `parse_item` on the way out, so the same validation that
guards a seed file guards a hand-edited row: a price with decimals or a zero-width sofa
fails here rather than in a buyer's total.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from furnitureos.modules.catalogue.item import Item, load_seed_items, parse_item
from furnitureos.modules.catalogue.models import ItemRow


def list_items(session: Session) -> list[Item]:
    """The whole catalogue, validated, grouped by category then name.

    The order is the store's rather than Postgres's: the panel draws category chips in
    this order, and a list that reshuffles between reloads looks broken.
    """
    rows = session.scalars(select(ItemRow).order_by(ItemRow.category, ItemRow.name))
    return [_to_item(row) for row in rows]


def resolve_items(session: Session, item_ids: Iterable[str]) -> dict[str, Item]:
    """Look up items by id, keyed by id, omitting any that do not exist.

    The lookup a plan needs: plans store item ids and quantities and never prices, so
    every price a buyer sees resolves through here against today's catalogue. Omitting
    unknown ids rather than raising lets the caller decide whether that is a 404
    (issue 05's validation) or an empty line (a catalogue that lost an item).
    """
    wanted = list(dict.fromkeys(item_ids))
    if not wanted:
        return {}

    rows = session.scalars(select(ItemRow).where(ItemRow.id.in_(wanted)))
    return {row.id: _to_item(row) for row in rows}


def seed_items(session: Session, overrides: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Load the seed catalogue into the database, upserting by id.

    Idempotent, and re-running picks up edits. Until the catalogue admin UI exists
    (post-v1), this is how a price changes: edit the seed, re-seed, deploy.
    """
    seeded: list[str] = []

    for item in load_seed_items():
        override = (overrides or {}).get(item.id)
        if override:
            item = parse_item({**_to_raw(item), **override})

        row = session.get(ItemRow, item.id)
        if row is None:
            session.add(_to_row(item))
        else:
            _update_row(row, item)

        seeded.append(item.id)

    session.flush()
    return seeded


def _to_item(row: ItemRow) -> Item:
    return parse_item(_row_as_raw(row))


def _row_as_raw(row: ItemRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "width_m": row.width_m,
        "depth_m": row.depth_m,
        "height_m": row.height_m,
        "price_vnd": row.price_vnd,
        "preset_ref": row.preset_ref,
        "photo_url": row.photo_url,
        "stock_qty": row.stock_qty,
        "lead_time_days": row.lead_time_days,
    }


def _to_raw(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "width_m": item.width_m,
        "depth_m": item.depth_m,
        "height_m": item.height_m,
        "price_vnd": item.price_vnd,
        "preset_ref": item.preset_ref,
        "photo_url": item.photo_url,
        "stock_qty": item.stock_qty,
        "lead_time_days": item.lead_time_days,
    }


def _to_row(item: Item) -> ItemRow:
    row = ItemRow(id=item.id)
    _update_row(row, item)
    return row


def _update_row(row: ItemRow, item: Item) -> None:
    row.name = item.name
    row.category = item.category
    row.width_m = item.width_m
    row.depth_m = item.depth_m
    row.height_m = item.height_m
    row.price_vnd = item.price_vnd
    row.preset_ref = item.preset_ref
    row.photo_url = item.photo_url
    row.stock_qty = item.stock_qty
    row.lead_time_days = item.lead_time_days
