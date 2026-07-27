"""Storage for catalogue items.

Columns, not a JSONB document — the opposite call to `units`, and for the opposite
reason. A unit plan is read and written whole; a catalogue is filtered, sorted and
resolved by id, and issue 08 recomputes prices from it on the server.

`price_vnd` is `BigInteger`. Vietnamese dong has no fractional unit, so `numeric(10,2)`
would be wrong twice over: it invites decimals that cannot exist, and ten digits runs
out somewhere around a bedroom set.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from furnitureos.core.db import Base


class ItemRow(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # True metres. The same numbers drive the drawn size and the collision size, which
    # is the whole reason the planner can promise "it fits".
    width_m: Mapped[float] = mapped_column(Float, nullable=False)
    depth_m: Mapped[float] = mapped_column(Float, nullable=False)
    height_m: Mapped[float] = mapped_column(Float, nullable=False)

    price_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    preset_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Present, maintained by nobody, and deliberately absent from the wire format. See
    # schemas.py: a stock number nobody updates is worse on screen than no number.
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
