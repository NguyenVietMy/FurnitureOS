"""Catalogue routes.

Public and unauthenticated, like the gallery: the catalogue is what the buyer came to
browse. Filtering and search happen in the browser — twenty items today, a hundred at
the ceiling the panel is built for, and a round trip per keystroke buys nothing at that
size.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from furnitureos.core.db import get_session
from furnitureos.modules.catalogue.schemas import ItemOut
from furnitureos.modules.catalogue.service import list_items

router = APIRouter(prefix="/api/items", tags=["catalogue"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[ItemOut])
def read_items(session: SessionDep) -> list[ItemOut]:
    return [ItemOut.from_item(item) for item in list_items(session)]
