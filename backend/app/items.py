"""Items and categories. Every call goes through the user's own token, so Row Level Security does the access check."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import db_for, storage_for
from .db import Rest
from .photos import remove_item_photos
from .storage import Storage

router = APIRouter()

Condition = Literal['new', 'like_new', 'very_good', 'good', 'fair', 'poor']
Intent = Literal['keep', 'maybe_sell', 'sell']


class ItemCreate(BaseModel):
    """Everything a user may set. Unknown fields (owner_id, version, id...) are rejected, not ignored."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=300)
    category_id: UUID
    release_id: UUID | None = None
    parent_item_id: UUID | None = None
    occasion_id: UUID | None = None
    giver_id: UUID | None = None
    source: str | None = Field(default=None, max_length=300)
    acquired_on: date | None = None
    date_is_approximate: bool = False
    condition_grade: Condition | None = None
    sealed: bool = False
    intent: Intent = 'keep'
    thank_you_sent: bool = False
    price_paid: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=5000)
    # On every item and searched across categories, so columns rather than category fields (attributes).
    franchise: str | None = Field(default=None, max_length=300)
    brand: str | None = Field(default=None, max_length=300)
    signed_by: str | None = Field(default=None, max_length=300)
    attributes: dict = Field(default_factory=dict)


class ItemUpdate(BaseModel):
    """A partial edit. `version` is the version the client last read: a stale one is rejected (409).
    Only fields the client sent are changed, so an explicit null clears a nullable field."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    category_id: UUID | None = None
    release_id: UUID | None = None
    parent_item_id: UUID | None = None
    occasion_id: UUID | None = None
    giver_id: UUID | None = None
    source: str | None = Field(default=None, max_length=300)
    acquired_on: date | None = None
    date_is_approximate: bool | None = None
    condition_grade: Condition | None = None
    sealed: bool | None = None
    intent: Intent | None = None
    thank_you_sent: bool | None = None
    price_paid: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=5000)
    franchise: str | None = Field(default=None, max_length=300)
    brand: str | None = Field(default=None, max_length=300)
    signed_by: str | None = Field(default=None, max_length=300)
    attributes: dict | None = None

    @model_validator(mode='after')
    def _valid_edit(self):
        sent = self.model_fields_set - {'version'}
        if not sent:
            raise ValueError('nothing to update')
        for required in ('name', 'category_id', 'date_is_approximate', 'sealed', 'intent', 'thank_you_sent',
                         'attributes'):
            if required in sent and getattr(self, required) is None:
                raise ValueError(f'{required} cannot be null')
        return self


@router.get('/categories')
async def list_categories(db: Rest = Depends(db_for)):
    """Built-in categories plus the user's own (RLS decides which). The description says what belongs in each;
    the picker searches it."""
    return await db.select('categories', {'select': 'id,parent_id,name,owner_id,description', 'order': 'name.asc'})


@router.get('/categories/{category_id}/fields')
async def category_fields(category_id: UUID, db: Rest = Depends(db_for)):
    """The fields for a category, including those inherited from its ancestors."""
    return await db.rpc('category_fields', {'p_category_id': str(category_id)})


@router.get('/items')
async def list_items(
    category_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
    db: Rest = Depends(db_for),
):
    """Newest first. Keyset pagination: pass the last row's created_at and id as before_created_at and before_id."""
    if (before_created_at is None) != (before_id is None):
        raise HTTPException(422, 'before_created_at and before_id go together')
    params = {'select': '*', 'order': 'created_at.desc,id.desc', 'limit': str(limit)}
    if category_id:
        params['category_id'] = f'eq.{category_id}'
    if before_created_at:
        ts = before_created_at.isoformat()
        params['or'] = f'(created_at.lt."{ts}",and(created_at.eq."{ts}",id.lt.{before_id}))'
    return await db.select('items', params)


@router.get('/items/{item_id}')
async def get_item(item_id: UUID, db: Rest = Depends(db_for)):
    rows = await db.select('items', {'select': '*', 'id': f'eq.{item_id}'})
    if not rows:
        raise HTTPException(404, 'No such item')
    return rows[0]


@router.post('/items', status_code=201)
async def create_item(body: ItemCreate, db: Rest = Depends(db_for)):
    # owner_id is not sent: the column defaults to auth.uid() and the RLS policy requires it to match.
    rows = await db.insert('items', body.model_dump(mode='json'))
    return rows[0]


@router.patch('/items/{item_id}')
async def update_item(item_id: UUID, body: ItemUpdate, db: Rest = Depends(db_for)):
    values = body.model_dump(mode='json', exclude={'version'}, exclude_unset=True)
    rows = await db.update('items', {'id': f'eq.{item_id}', 'version': f'eq.{body.version}'}, values)
    if rows:
        return rows[0]
    # No row changed: either it does not exist or is not yours, or someone saved first.
    current = await db.select('items', {'select': '*', 'id': f'eq.{item_id}'})
    if not current:
        raise HTTPException(404, 'No such item')
    raise HTTPException(409, detail={'message': 'Changed since you loaded it', 'current': current[0]})


@router.delete('/items/{item_id}', status_code=204)
async def delete_item(item_id: UUID, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    await remove_item_photos(db, storage, item_id)  # the database drops the photo rows with the item, not the files
    rows = await db.delete('items', {'id': f'eq.{item_id}'})
    if not rows:
        raise HTTPException(404, 'No such item')
