"""The units service: seeding, and reading a unit back out as a validated plan."""

import pytest
from sqlalchemy.orm import Session

from furnitureos.modules.units import UnitPlanError, get_unit, seed_units


def test_seeding_loads_the_placeholder_unit(session: Session) -> None:
    seeded = seed_units(session)

    assert "sunrise-b" in seeded


def test_seeding_is_idempotent(session: Session) -> None:
    """Seeds run on every boot in development, so running twice must not duplicate."""
    seed_units(session)
    seed_units(session)

    plan = get_unit(session, "sunrise-b")
    assert plan is not None


def test_seeding_updates_a_changed_plan(session: Session) -> None:
    """Editing a seed file and re-seeding must take effect, or iteration is painful."""
    seed_units(session)
    seed_units(session, overrides={"sunrise-b": {"ceiling_height_m": 3.1}})

    plan = get_unit(session, "sunrise-b")
    assert plan is not None
    assert plan.ceiling_height_m == pytest.approx(3.1)


def test_get_unit_returns_a_parsed_plan(session: Session) -> None:
    seed_units(session)

    plan = get_unit(session, "sunrise-b")

    assert plan is not None
    assert plan.slug == "sunrise-b"
    assert plan.bedrooms == 2
    assert plan.area_m2 == pytest.approx(74.0)
    assert len(plan.walls) == 10


def test_get_unit_returns_none_for_an_unknown_slug(session: Session) -> None:
    seed_units(session)

    assert get_unit(session, "does-not-exist") is None


def test_stored_plans_are_validated_on_read(session: Session) -> None:
    """A corrupt row must fail loudly rather than reach the renderer as broken geometry."""
    # Reaching past the module's public surface is allowed here and only here: writing a
    # deliberately corrupt row is exactly the thing the public API refuses to do.
    from furnitureos.modules.units.models import UnitRow

    session.add(UnitRow(slug="broken", payload={"outline": [[0.0, 0.0]]}))
    session.flush()

    with pytest.raises(UnitPlanError):
        get_unit(session, "broken")
