"""Reading and seeding unit plans.

Plans are validated on the way out as well as the way in. A row can be edited by hand
or written by a future tracer tool, and broken geometry must fail here rather than
arrive at the renderer as an unexplained hole in a wall.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from furnitureos.modules.units.models import UnitRow
from furnitureos.modules.units.plan import SEEDS_DIR, UnitPlan, parse_unit_plan


def get_unit(session: Session, slug: str) -> UnitPlan | None:
    """Return a validated plan, or None if no unit has that slug."""
    row = session.get(UnitRow, slug)
    if row is None:
        return None
    return parse_unit_plan(row.payload)


def list_units(session: Session) -> list[UnitPlan]:
    """Every unit, validated, in a stable order.

    Plans rather than rows, because the gallery's metadata — area, bedroom count — is
    derived from the geometry and not stored beside it. Ordering is fixed here so a
    reload cannot reshuffle the grid on Postgres's whim.
    """
    rows = session.scalars(select(UnitRow).order_by(UnitRow.slug))
    return [parse_unit_plan(row.payload) for row in rows]


def seed_units(session: Session, overrides: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Load every seed file into the database, upserting by slug.

    Idempotent, and re-running picks up edits to the seed files — development involves
    editing a plan and looking at it, and that loop should not require a reset.
    """
    seeded: list[str] = []

    for path in sorted(SEEDS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if overrides and payload["slug"] in overrides:
            payload.update(overrides[payload["slug"]])

        plan = parse_unit_plan(payload)

        row = session.get(UnitRow, plan.slug)
        if row is None:
            session.add(UnitRow(slug=plan.slug, payload=payload))
        else:
            row.payload = payload

        seeded.append(plan.slug)

    session.flush()
    return seeded
