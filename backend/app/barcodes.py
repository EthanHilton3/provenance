"""Barcode lookup: a barcode -> the shared release, with no AI call.

Order, cheapest first:
1. `releases` by barcode, on its unique index, as the user (every signed-in user may read releases). No outside call.
2. `catalog_cache` (backend only): a cached hit or a cached miss, until it expires.
3. UPCitemdb, if the shared daily budget allows (begin_catalog_call() in the database). Hits are cached for 30 days
   and misses for 7 (the catalog may add the product later). A 429, a timeout or a server error is never cached, so
   the next scan asks again; a 429 also pauses every lookup for as long as it asks.

A hit becomes a shared release through release_from_catalog() (INSERT ... ON CONFLICT DO NOTHING, as the service
role): two people scanning the same new barcode at once get one release, and an existing release is never changed.
Users cannot write releases themselves. Edition and format are left empty on the release: the catalog rarely states
them reliably, so they are hints for the card (upc.hints()), and what the owner answers is saved on their item.

Every code passes gtin.parse() (check digit, canonical form) before any of this.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import gtin
from .auth import AuthUser, current_user, db_for
from .config import get_settings
from .db import DbError, Rest, service_db
from .upc import UpcItemDb, UpcResult, hints

logger = logging.getLogger(__name__)
router = APIRouter()

PROVIDER = 'upcitemdb'
HIT_TTL = timedelta(days=30)
MISS_TTL = timedelta(days=7)
RELEASE_COLUMNS = 'id,barcode,title,edition,format,publisher,release_year,verified,attributes'

Status = Literal['found', 'not_found', 'unavailable']
Source = Literal['releases', 'cache', 'upcitemdb'] | None


class Lookup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(max_length=40)


def _public_release(r: dict) -> dict:
    return {k: r.get(k) for k in RELEASE_COLUMNS.split(',')}


def _product_of(release: dict) -> dict:
    """The catalog fields a release keeps, in the shape hints() reads."""
    cat = (release.get('attributes') or {}).get('catalog') or {}
    return {'title': release.get('title'), 'brand': release.get('publisher'), 'category': cat.get('category'),
            'model': cat.get('model')}


def _answer(bc: gtin.Barcode, status: Status, source: Source, release: dict | None = None, *,
            message: str | None = None, reason: str | None = None) -> dict:
    return {'barcode': bc.code, 'barcode_kind': bc.kind, 'status': status, 'source': source,
            'release': _public_release(release) if release else None,
            'hints': hints(_product_of(release), bc.kind) if release else None,
            'message': message, 'reason': reason}


async def _release(svc: Rest, bc: gtin.Barcode, product: dict, user: AuthUser) -> dict:
    attrs = {'catalog': {'source': PROVIDER, 'category': product.get('category'), 'model': product.get('model')}}
    return await svc.rpc('release_from_catalog', {
        'p_barcode': bc.code, 'p_title': product['title'], 'p_publisher': product.get('brand'),
        'p_attributes': attrs, 'p_created_by': user.id,
    })


async def _cache(svc: Rest, key: str, value: dict, ttl: timedelta) -> None:
    now = datetime.now(timezone.utc)
    try:
        await svc.upsert('catalog_cache', {'key': key, 'response': value, 'fetched_at': now.isoformat(),
                                           'expires_at': (now + ttl).isoformat()}, on_conflict='key')
    except DbError as e:  # the lookup still worked; the next scan just asks again
        logger.error('Could not cache %s: %s', key, e)


async def _finish(svc: Rest, call_id: int, result: UpcResult) -> None:
    values = {'http_status': result.http_status, 'outcome': result.outcome, 'retry_after': None}
    if result.outcome == 'rate_limited':
        values['retry_after'] = (datetime.now(timezone.utc) + timedelta(seconds=result.retry_after or 60)).isoformat()
        logger.warning('UPCitemdb rate limited us for %.0f s (%s)', result.retry_after or 60, result.headers)
    elif result.outcome == 'error':
        logger.warning('UPCitemdb lookup failed: %s', result.reason)
    try:
        await svc.update('catalog_calls', {'id': f'eq.{call_id}'}, values)
    except DbError as e:
        logger.error('Could not record catalog call %s: %s', call_id, e)


@router.post('/barcodes/lookup')
async def lookup(body: Lookup, request: Request, user: AuthUser = Depends(current_user), db: Rest = Depends(db_for)):
    """`status`: found (with the release and card hints), not_found (offer the photo or add by hand), or unavailable
    (budget spent, rate limited, catalog down: the same two choices, and scanning again later may find it).
    422 if the code is not a valid barcode."""
    try:
        bc = gtin.parse(body.code)
    except gtin.BadBarcode as e:
        raise HTTPException(422, detail={'message': str(e), 'reason': 'bad_barcode'}) from None

    rows = await db.select('releases', {'select': RELEASE_COLUMNS, 'barcode': f'eq.{bc.code}'})
    if rows:
        return _answer(bc, 'found', 'releases', rows[0])

    http = request.app.state.http
    svc = service_db(http)
    key = f'upc:{bc.code}'
    cached = await svc.select('catalog_cache', {'select': 'response', 'key': f'eq.{key}',
                                                'expires_at': f'gt.{datetime.now(timezone.utc).isoformat()}'})
    if cached:
        value = cached[0]['response'] or {}
        if value.get('found') and value.get('product', {}).get('title'):
            return _answer(bc, 'found', 'cache', await _release(svc, bc, value['product'], user))
        return _answer(bc, 'not_found', 'cache')

    settings = get_settings()
    try:
        call_id = await svc.rpc('begin_catalog_call', {
            'p_provider': PROVIDER, 'p_user': user.id, 'p_daily': settings.upc_daily_budget,
            'p_per_user': settings.upc_per_user_daily, 'p_per_minute': settings.upc_per_minute,
        })
    except DbError as e:
        info = e.body if isinstance(e.body, dict) else {}
        if info.get('code') in ('PT429', 'PT503'):
            return _answer(bc, 'unavailable', None, message=info.get('message'), reason=info.get('details'))
        raise

    result = await UpcItemDb(http, settings.upcitemdb_url).lookup(bc)
    await _finish(svc, call_id, result)
    if result.outcome == 'hit':
        await _cache(svc, key, {'source': PROVIDER, 'found': True, 'product': result.product}, HIT_TTL)
        return _answer(bc, 'found', 'upcitemdb', await _release(svc, bc, result.product, user))
    if result.outcome == 'miss':
        await _cache(svc, key, {'source': PROVIDER, 'found': False}, MISS_TTL)
        return _answer(bc, 'not_found', 'upcitemdb')
    if result.outcome == 'rate_limited':
        return _answer(bc, 'unavailable', None, reason='rate_limited',
                       message='The barcode catalog is busy; try again in a little while')
    return _answer(bc, 'unavailable', None, reason='catalog_error',
                   message="The barcode catalog didn't answer; try again in a little while")
