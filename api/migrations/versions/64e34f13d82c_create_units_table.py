"""create units table

Revision ID: 64e34f13d82c
Revises:
Create Date: 2026-07-27 09:39:28.897067
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "64e34f13d82c"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The whole plan lives in one JSONB column: it is read and written whole and is
    # never queried by its parts, so splitting it into tables would buy nothing.
    op.create_table(
        "units",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug"),
    )


def downgrade() -> None:
    op.drop_table("units")
