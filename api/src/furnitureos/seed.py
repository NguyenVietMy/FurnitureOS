"""Load every module's seed data into the configured database.

Run with `uv run python -m furnitureos.seed`. Idempotent: it upserts, so re-running
after editing a seed file republishes the edit.
"""

from furnitureos.core.db import SessionLocal
from furnitureos.modules.units import seed_units


def main() -> None:
    with SessionLocal() as session:
        slugs = seed_units(session)
        session.commit()
    for slug in slugs:
        print(f"seeded unit {slug}")


if __name__ == "__main__":
    main()
