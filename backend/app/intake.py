"""Intake jobs: queue uploaded photos for the AI worker, read back its proposals, and confirm or discard them.
No AI call happens here.

Every write goes through a database function called with the signed-in user's token, so the owner is auth.uid():
* create_intake_jobs(): photo ownership, the daily limit, the batch occasion and the photo-to-job links.
* confirm_intake_job(): creates the items, links the photo, marks the job done, in one transaction, after locking the
  job row; a second confirm (double tap, another tab) gets a 409 and creates nothing.
* discard_intake_job() and retry_intake_job().
Reads go through RLS. The worker (worker.py) fills in `card`.

The card is the model's output and is never trusted: what gets saved is what the owner sends to confirm, validated
here against the same ItemCreate model as a hand-made item, and checked again by the database function.

One job per photo. "single": one item in the photo (Luna). "group": many items in one photo (Sol). A group photo
yields many items; each item after the first gets its own copy of the photo file (copied inside Storage, as the
user), so every item owns its photo exactly as a hand-made one does.
"""
import asyncio
import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import gtin
from .auth import AuthUser, current_user, db_for, storage_for
from .db import DbError, Rest
from .items import ItemCreate
from .storage import SIGNED_URL_SECONDS, Storage, StorageError

logger = logging.getLogger(__name__)
router = APIRouter()

COLUMNS = ('id,mode,status,card,error,attempts,max_attempts,occasion_id,barcode,created_at,updated_at,'
           'photos(id,storage_path,item_id,width,height),items!items_intake_job_fk(id,name)')
Status = Literal['queued', 'processing', 'needs_review', 'done', 'failed', 'discarded']
OPEN = ('queued', 'processing', 'needs_review', 'failed')  # still needs something from the worker or the owner
HAS_CARD = {'needs_review', 'done'}
COPY_AT_ONCE = 4


class JobCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    photo_ids: list[UUID] = Field(min_length=1, max_length=50)
    mode: Literal['single', 'group']
    occasion_id: UUID | None = None
    # A barcode the catalog did not know ("photograph the box" after a miss): kept with the one photo of one item.
    barcode: str | None = Field(default=None, max_length=40)

    @model_validator(mode='after')
    def _barcode(self):
        if self.barcode is not None:
            try:
                self.barcode = gtin.parse(self.barcode).code
            except gtin.BadBarcode as e:
                raise ValueError(str(e)) from None
            if self.mode != 'single' or len(self.photo_ids) != 1:
                raise ValueError('A barcode goes with one photo of one item')
        return self


class Confirm(BaseModel):
    """What the owner saves: one item per card or per selected grid row, as edited. Same rules as a hand-made item."""
    model_config = ConfigDict(extra='forbid')
    items: list[ItemCreate] = Field(min_length=1, max_length=100)


def _public(row: dict, urls: dict | None = None) -> dict:
    out = {k: v for k, v in row.items() if k not in ('photos', 'items')}
    photos = row.get('photos') or []
    out['photo_ids'] = [p['id'] for p in photos]
    first = next((p for p in photos if p.get('storage_path')), None)
    out['photo'] = None
    if first:
        out['photo'] = {'id': first['id'], 'width': first.get('width'), 'height': first.get('height'),
                        'url': (urls or {}).get(first['storage_path']), 'url_expires_in': SIGNED_URL_SECONDS}
    out['items'] = row.get('items') or []
    if out.get('status') not in HAS_CARD:
        out['card'] = None
    return out


async def _with_urls(rows: list[dict], storage: Storage) -> list[dict]:
    """One signing call for the first photo of every job (a missing file just gets no URL)."""
    paths = [p['storage_path'] for r in rows for p in (r.get('photos') or [])[:1] if p.get('storage_path')]
    urls = {}
    if paths:
        try:
            urls = await storage.sign(paths)
        except StorageError as e:  # the list is still useful without pictures
            logger.warning('Could not sign intake photo URLs: %s', e)
    return [_public(r, urls) for r in rows]


async def _job_row(db: Rest, job_id: UUID) -> dict:
    rows = await db.select('intake_jobs', {'select': COLUMNS, 'id': f'eq.{job_id}'})
    if not rows:  # RLS hides other people's jobs, so theirs is a 404 too
        raise HTTPException(404, 'No such intake job')
    return rows[0]


async def _remove_files(storage: Storage, paths: list[str], why: str) -> None:
    if not paths:
        return
    try:
        await storage.remove(paths)
    except StorageError as e:
        logger.error('Orphaned photo copies %s (%s), and the cleanup failed too: %s', paths, why, e)


@router.post('/intake/jobs', status_code=201)
async def create_jobs(body: JobCreate, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    """404 if a photo or the occasion is not yours (or does not exist), 409 if a photo is already on an item or in
    intake, 429 over the daily limit. Nothing is created unless every photo is accepted."""
    args = {'p_photo_ids': [str(p) for p in body.photo_ids], 'p_mode': body.mode}
    if body.occasion_id:
        args['p_occasion_id'] = str(body.occasion_id)
    if body.barcode:
        args['p_barcode'] = body.barcode
    created = await db.rpc('create_intake_jobs', args)
    ids = [r['id'] for r in created]
    rows = await db.select('intake_jobs', {'select': COLUMNS, 'id': f'in.({",".join(ids)})'})
    order = {jid: n for n, jid in enumerate(ids)}
    return await _with_urls(sorted(rows, key=lambda r: order.get(r['id'], len(order))), storage)


@router.get('/intake/jobs')
async def list_jobs(status: Status | None = None, open: bool = False, limit: int = Query(50, ge=1, le=200),
                    db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    """Newest first. `open=true`: only jobs still waiting on the worker or on you (queued, processing, needs review,
    failed). `card` is filled in once the worker has a proposal; `photo.url` is signed for an hour."""
    if status and open:
        raise HTTPException(422, 'Use status or open, not both')
    params = {'select': COLUMNS, 'order': 'created_at.desc,id.desc', 'limit': str(limit)}
    if status:
        params['status'] = f'eq.{status}'
    elif open:
        params['status'] = f'in.({",".join(OPEN)})'
    return await _with_urls(await db.select('intake_jobs', params), storage)


@router.get('/intake/jobs/{job_id}')
async def get_job(job_id: UUID, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    return (await _with_urls([await _job_row(db, job_id)], storage))[0]


@router.post('/intake/jobs/{job_id}/confirm')
async def confirm_job(job_id: UUID, body: Confirm, user: AuthUser = Depends(current_user), db: Rest = Depends(db_for),
                      storage: Storage = Depends(storage_for)):
    """Saves the items and finishes the job. 409 (with the job and the items it already made) if it was confirmed
    already or is not ready; 422 if an item's category, occasion, person or parent is not yours."""
    job = await _job_row(db, job_id)
    if job['status'] == 'done':
        raise HTTPException(409, detail={'message': 'These items are already saved', 'job': _public(job)})
    if job['status'] not in ('needs_review', 'failed'):
        raise HTTPException(409, detail={'message': 'The AI has not finished reading this photo', 'job': _public(job)})

    # One copy of the photo for each item after the first, made before the transaction (Storage is not in it) and
    # removed again if the transaction does not commit.
    source = next((p for p in job.get('photos') or [] if p.get('item_id') is None), None)
    copies: list[dict] = []
    if source and len(body.items) > 1:
        copies = [{'id': str(cid), 'storage_path': f'{user.id}/{cid}.jpg'} for cid in (uuid4() for _ in body.items[1:])]
        gate = asyncio.Semaphore(COPY_AT_ONCE)

        async def one(c):
            async with gate:
                await storage.copy(source['storage_path'], c['storage_path'])

        results = await asyncio.gather(*(one(c) for c in copies), return_exceptions=True)
        if any(isinstance(r, BaseException) for r in results):
            made = [c['storage_path'] for c, r in zip(copies, results) if not isinstance(r, BaseException)]
            await _remove_files(storage, made, 'photo copy failed')
            first = next(r for r in results if isinstance(r, BaseException))
            logger.error('Could not copy the group photo for job %s: %s', job_id, first)
            raise HTTPException(502, detail={'message': 'Could not copy the photo for each item; nothing was saved, try again'})

    items = [i.model_dump(mode='json') for i in body.items]
    try:
        created = await db.rpc('confirm_intake_job', {'p_job_id': str(job_id), 'p_items': items, 'p_copies': copies})
    except DbError as e:
        await _remove_files(storage, [c['storage_path'] for c in copies], 'confirm did not commit')
        code = e.body.get('code') if isinstance(e.body, dict) else None
        if code == 'PT409':  # lost a race with another tab, or the job changed since we read it
            raise HTTPException(409, detail={'message': e.body.get('message'), 'job': _public(await _job_row(db, job_id))}) from None
        if code == '23503':
            raise HTTPException(422, detail={'message': 'An occasion, person or containing item is not yours or no longer exists'}) from None
        raise
    return {'items': created, 'job': (await _with_urls([await _job_row(db, job_id)], storage))[0]}


@router.post('/intake/jobs/{job_id}/discard', status_code=204)
async def discard_job(job_id: UUID, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    """Throws the card away and deletes its photo (file first, then the row, as photos.py does). The job row stays,
    marked discarded, so it still counts toward the daily limit. Discarding again finishes a half-done cleanup."""
    photos = await db.rpc('discard_intake_job', {'p_job_id': str(job_id)})
    if not photos:
        return Response(status_code=204)
    try:
        await storage.remove([p['storage_path'] for p in photos])
    except StorageError as e:
        logger.error('Discarded job %s but could not delete its photo file: %s', job_id, e)
        raise HTTPException(502, detail={'message': 'Discarded, but the photo could not be deleted; discard again to finish'}) from None
    await db.delete('photos', {'id': f'in.({",".join(p["photo_id"] for p in photos)})', 'item_id': 'is.null'})
    return Response(status_code=204)


@router.post('/intake/jobs/{job_id}/retry')
async def retry_job(job_id: UUID, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    """A failed job back in the queue with fresh attempts; counts as one more photo toward the daily limit."""
    await db.rpc('retry_intake_job', {'p_job_id': str(job_id)})
    return (await _with_urls([await _job_row(db, job_id)], storage))[0]
