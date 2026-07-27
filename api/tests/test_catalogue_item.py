"""The catalogue's domain rules, tested without a database.

Two invariants carry the whole product promise. Dimensions are true metres, because
"it fits" in the planner has to mean "it fits" on delivery day. Prices are whole VND
integers, because VND has no fractional unit and a float path anywhere is a rounding
bug waiting for a five-figure total.
"""

import pytest

from furnitureos.modules.catalogue import ItemError, load_seed_items, parse_item

VALID = {
    "id": "sofa-3-seat",
    "name": "Linen 3-seat sofa",
    "category": "seating",
    "width_m": 2.1,
    "depth_m": 0.92,
    "height_m": 0.84,
    "price_vnd": 12_500_000,
    "preset_ref": "sofa-3",
}


def test_parses_a_well_formed_item() -> None:
    item = parse_item(VALID)

    assert item.id == "sofa-3-seat"
    assert item.price_vnd == 12_500_000
    assert item.width_m == pytest.approx(2.1)


def test_photo_is_optional() -> None:
    """Issue 13 supplies real photographs; a placeholder catalogue has none."""
    assert parse_item(VALID).photo_url is None


def test_stock_defaults_to_nothing_and_is_never_required() -> None:
    """The columns exist for later. Nothing in v1 renders them, so nothing demands them."""
    item = parse_item(VALID)

    assert item.stock_qty == 0
    assert item.lead_time_days == 0


@pytest.mark.parametrize("dimension", ["width_m", "depth_m", "height_m"])
def test_dimensions_must_be_positive(dimension: str) -> None:
    with pytest.raises(ItemError):
        parse_item({**VALID, dimension: 0})


def test_price_must_be_a_whole_number_of_dong() -> None:
    """VND has no fractional unit. A price with decimals is a data-entry mistake."""
    with pytest.raises(ItemError):
        parse_item({**VALID, "price_vnd": 12_500_000.5})


def test_price_must_not_be_negative() -> None:
    with pytest.raises(ItemError):
        parse_item({**VALID, "price_vnd": -1})


def test_id_is_required() -> None:
    with pytest.raises(ItemError):
        parse_item({**VALID, "id": ""})


def test_preset_ref_is_required() -> None:
    """Every item resolves to a model, even while every model is a placeholder box."""
    with pytest.raises(ItemError):
        parse_item({**VALID, "preset_ref": ""})


# --- the seeded placeholder catalogue ---------------------------------------------


def test_seed_catalogue_is_roughly_twenty_items() -> None:
    """v1 seeds ~20; the panel is built for ~100. Both numbers are in issue 03."""
    assert 15 <= len(load_seed_items()) <= 30


def test_seed_ids_are_unique() -> None:
    items = load_seed_items()

    assert len({item.id for item in items}) == len(items)


def test_seed_prices_are_integers() -> None:
    for item in load_seed_items():
        assert isinstance(item.price_vnd, int)


def test_seed_covers_several_categories() -> None:
    """The panel's category chips need something to chip."""
    assert len({item.category for item in load_seed_items()}) >= 4
