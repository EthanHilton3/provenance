"""Intake jobs: queue uploaded photos for the AI worker, then read back its proposals. No AI call happens here.

Jobs are created by the database function create_intake_jobs(), called with the signed-in user's token: the owner is
auth.uid(), and the photo ownership check, the daily limit and the photo-to-job links all happen in one transaction.
Reads go through RLS. The worker (worker.py) fills in `card`; nothing here changes a job after creating it.

One job per photo. "single": one item in the photo (Luna). "group": many items in one photo (Sol).
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import db_for
from .db import Rest

router = APIRouter()

COLUMNS = 'id,mode,status,card,error,attempts,max_attempts,created_at,updated_at,photos(id)'
Status = Literal['queued', 'processing', 'needs_review', 'done', 'failed']
HAS_CARD = {'needs_review', 'done'}


class JobCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    photo_ids: list[UUID] = Field(min_length=1, max_length=50)
    mode: Literal['single', 'group']


def _public(row: dict) -> dict:
    out = {k: v for k, v in row.items() if k != 'photos'}
    out['photo_ids'] = [p['id'] for p in row.get('photos') or []]
    if out.get('status') not in HAS_CARD:
        out['card'] = None
    return out


@router.post('/intake/jobs', status_code=201)
async def create_jobs(body: JobCreate, db: Rest = Depends(db_for)):
    """404 if a photo is not yours (or does not exist), 409 if one is already on an item or in intake, 429 over the
    daily limit. Nothing is created unless every photo is accepted."""
    created = await db.rpc('create_intake_jobs', {'p_photo_ids': [str(p) for p in body.photo_ids], 'p_mode': body.mode})
    ids = [r['id'] for r in created]
    rows = await db.select('intake_jobs', {'select': COLUMNS, 'id': f'in.({",".join(ids)})'})
    order = {jid: n for n, jid in enumerate(ids)}
    return [_public(r) for r in sorted(rows, key=lambda r: order.get(r['id'], len(order)))]


@router.get('/intake/jobs')
async def list_jobs(status: Status | None = None, limit: int = Query(50, ge=1, le=200), db: Rest = Depends(db_for)):
    """Newest first. `card` is filled in once the worker has a proposal (status needs_review or done)."""
    params = {'select': COLUMNS, 'order': 'created_at.desc,id.desc', 'limit': str(limit)}
    if status:
        params['status'] = f'eq.{status}'
    return [_public(r) for r in await db.select('intake_jobs', params)]


@router.get('/intake/jobs/{job_id}')
async def get_job(job_id: UUID, db: Rest = Depends(db_for)):
    rows = await db.select('intake_jobs', {'select': COLUMNS, 'id': f'eq.{job_id}'})
    if not rows:  # RLS hides other people's jobs, so theirs is a 404 too
        raise HTTPException(404, 'No such intake job')
    return _public(rows[0])
