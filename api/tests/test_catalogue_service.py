"""The catalogue service: seeding, listing, and resolving ids.

`resolve_items` is the lookup issues 05 and 08 lean on — a plan stores item ids and
quantities and never prices, so every price the buyer sees is resolved from here.
"""

import pytest
from sqlalchemy.orm import Session

from furnitureos.modules.catalogue import (
    list_items,
    load_seed_items,
    resolve_items,
    seed_items,
)


def test_seeding_loads_the_placeholder_catalogue(session: Session) -> None:
    seeded = seed_items(session)

    assert len(seeded) >= 15


def test_seeding_is_idempotent(session: Session) -> None:
    """Seeds run on every boot in development, so running twice must not duplicate."""
    seed_items(session)
    seed_items(session)

    assert len(list_items(session)) == len(seed_items(session))


def test_seeding_updates_a_changed_item(session: Session) -> None:
    """Editing a seed file and re-seeding must take effect: prices change by seed edit."""
    seed_items(session)
    first = list_items(session)[0]
    seed_items(session, overrides={first.id: {"price_vnd": 999_000}})

    reseeded = {item.id: item for item in list_items(session)}
    assert reseeded[first.id].price_vnd == 999_000


def test_list_items_is_empty_before_seeding(session: Session) -> None:
    assert list_items(session) == []


def test_list_items_groups_by_category_then_name(session: Session) -> None:
    seed_items(session)

    keys = [(item.category, item.name) for item in list_items(session)]

    assert keys == sorted(keys)


def test_resolve_items_looks_up_by_id(session: Session) -> None:
    seed_items(session)
    wanted = list_items(session)[0]

    resolved = resolve_items(session, [wanted.id])

    assert resolved[wanted.id].price_vnd == wanted.price_vnd


def test_resolve_items_omits_ids_that_do_not_exist(session: Session) -> None:
    """The caller decides whether a missing id is a 404 or a silent drop; this reports."""
    seed_items(session)

    assert resolve_items(session, ["no-such-item"]) == {}


def test_resolve_items_with_no_ids_does_not_query_for_everything(session: Session) -> None:
    seed_items(session)

    assert resolve_items(session, []) == {}


def test_dimensions_survive_the_round_trip(session: Session) -> None:
    """A sofa entered 10cm narrow is a delivery-day argument, so this is not pedantry."""
    seed_items(session)
    seeded = load_seed_items()

    stored = {item.id: item for item in list_items(session)}
    for authored in seeded:
        assert stored[authored.id].width_m == pytest.approx(authored.width_m)
        assert stored[authored.id].depth_m == pytest.approx(authored.depth_m)
        assert stored[authored.id].height_m == pytest.approx(authored.height_m)


def test_prices_come_back_as_integers_not_floats(session: Session) -> None:
    """BIGINT in, int out. A float anywhere on this path is a rounding bug in a total."""
    seed_items(session)

    for item in list_items(session):
        assert isinstance(item.price_vnd, int)
