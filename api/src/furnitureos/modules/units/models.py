"""Storage for unit plans.

The plan is stored as a single JSONB payload rather than shredded into tables. The
geometry is read and written whole, never queried by its parts, and its shape is still
moving — a relational decomposition would buy nothing and cost a migration every time
the tracer learns a new trick.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from furnitureos.core.db import Base


class UnitRow(Base):
    __tablename__ = "units"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
