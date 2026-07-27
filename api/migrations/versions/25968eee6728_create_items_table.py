"""create items table

Revision ID: 25968eee6728
Revises: 64e34f13d82c
Create Date: 2026-07-27 11:17:52.060257
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "25968eee6728"
down_revision: str | None = "64e34f13d82c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Columns, not JSONB — the opposite call to `units`, because a catalogue is
    # filtered, sorted and resolved by id rather than read whole.
    #
    # price_vnd is BIGINT: dong has no fractional unit, so there is no float or numeric
    # path anywhere on this column by design.
    op.create_table(
        "items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("width_m", sa.Float(), nullable=False),
        sa.Column("depth_m", sa.Float(), nullable=False),
        sa.Column("height_m", sa.Float(), nullable=False),
        sa.Column("price_vnd", sa.BigInteger(), nullable=False),
        sa.Column("preset_ref", sa.String(length=64), nullable=False),
        sa.Column("photo_url", sa.String(length=512), nullable=True),
        # Stock exists and is never served. See modules/catalogue/schemas.py.
        sa.Column("stock_qty", sa.Integer(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_items_category"), "items", ["category"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_items_category"), table_name="items")
    op.drop_table("items")
