"""Unit routes.

Both are public and unauthenticated by design: the gallery is the front door of the
funnel, so there is no code to enter and no unit number to look up.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from furnitureos.core.db import get_session
from furnitureos.modules.units.schemas import UnitOut, UnitSummaryOut
from furnitureos.modules.units.service import get_unit, list_units

router = APIRouter(prefix="/api/units", tags=["units"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[UnitSummaryOut])
def read_units(session: SessionDep) -> list[UnitSummaryOut]:
    return [UnitSummaryOut.from_plan(plan) for plan in list_units(session)]


@router.get("/{slug}", response_model=UnitOut)
def read_unit(slug: str, session: SessionDep) -> UnitOut:
    plan = get_unit(session, slug)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"no unit named {slug!r}")
    return UnitOut.from_plan(plan)
