"""Unit routes.

Only lookup-by-slug in this slice. The gallery's list endpoint belongs to issue 02 and
is deliberately not built here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from furnitureos.core.db import get_session
from furnitureos.modules.units.schemas import UnitOut
from furnitureos.modules.units.service import get_unit

router = APIRouter(prefix="/api/units", tags=["units"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{slug}", response_model=UnitOut)
def read_unit(slug: str, session: SessionDep) -> UnitOut:
    plan = get_unit(session, slug)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"no unit named {slug!r}")
    return UnitOut.from_plan(plan)
