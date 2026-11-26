"""Occasions: how you got things ("Christmas 2025", "Yard sale 11/13/24"). Private, so RLS does the access check.

S10 needs only the list and create, for the intake screen's "these are all from..." picker. S14 adds the views.
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from .auth import db_for
from .db import Rest

router = APIRouter()

COLUMNS = 'id,name,kind,occurred_on,date_is_approximate,created_at'
Kind = Literal['holiday', 'birthday', 'wedding', 'sale', 'trip', 'purchase', 'other']


class OccasionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    kind: Kind = 'other'
    occurred_on: date | None = None
    date_is_approximate: bool = False


@router.get('/occasions')
async def list_occasions(db: Rest = Depends(db_for)):
    """Most recent first; undated ones after the dated ones."""
    return await db.select('occasions', {'select': COLUMNS, 'order': 'occurred_on.desc.nullslast,created_at.desc',
                                         'limit': '500'})


@router.post('/occasions', status_code=201)
async def create_occasion(body: OccasionCreate, db: Rest = Depends(db_for)):
    # owner_id is not sent: it defaults to auth.uid() and the RLS policy requires it to match.
    rows = await db.insert('occasions', body.model_dump(mode='json'))
    return {k: rows[0].get(k) for k in COLUMNS.split(',')}
