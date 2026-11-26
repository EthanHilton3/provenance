"""User-created shared releases and work links (S12).

POST /api/releases: when the owner confirms a card and chooses to share it, this makes the shared release (and its
work) from the catalog facts they approved, before the item is saved with its release_id. What is shared is fixed by
the request model, which accepts nothing else: the release's title, format and edition, the barcode if there is one,
and the work (a catalog entry, or "none of these": title, year and kind). Notes, photos, occasions, people, price,
location and condition stay on the private item. The shared rows record who created them (created_by), which only the
backend can read.

Duplicates: with a barcode, the unique index decides (an existing release is returned unchanged). Without one, the
release's canonical text is embedded (app/embeddings.py) and create_user_release() looks for a near-identical release
under a lock; if it finds one it creates nothing and returns status 'similar', and the card asks "this looks like an
existing release; use it?". "No, mine is different" sends the same request again with that release in `declined`.
Nothing is ever merged automatically. If the check cannot run (OpenAI down, a cap reached), status 'unavailable': the
card saves the item without a shared release rather than risk a duplicate.

A catalog work is never written from what the client sends: the API reads the entry's facts itself (Catalog.work()),
so a user cannot attach a made-up title to a TMDB id. Users still cannot write works or releases; this goes through
service-role database functions, and an existing shared release or work is never changed by another user.
"""
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import gtin
from .auth import AuthUser, current_user
from .catalog import REF_RE, Catalog, Unavailable
from .config import Settings, get_settings
from .db import Rest, service_db
from .embeddings import EmbeddingError, FakeEmbeddings, OpenAIEmbeddings, canonical_text, embed_release_text, norm_format

logger = logging.getLogger(__name__)
router = APIRouter()

RELEASE_FIELDS = ('id', 'barcode', 'title', 'edition', 'format', 'publisher', 'release_year', 'verified')
WORK_FIELDS = ('id', 'title', 'year', 'kind', 'catalog_ref')
SIMILAR_FIELDS = ('id', 'barcode', 'title', 'edition', 'format', 'release_year', 'work_title', 'work_year')


class NewWork(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1000, le=3000)
    kind: Literal['movie', 'tv', 'book', 'game', 'other'] = 'other'


class WorkPick(BaseModel):
    """A catalog candidate's ref, or a new work ("none of these")."""
    model_config = ConfigDict(extra='forbid')
    ref: str | None = Field(default=None, max_length=60)
    new: NewWork | None = None

    @model_validator(mode='after')
    def _one(self):
        if (self.ref is None) == (self.new is None):
            raise ValueError('Send a catalog ref or a new work')
        if self.ref is not None and not REF_RE.match(self.ref):
            raise ValueError('Not a catalog reference')
        return self


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    format: str | None = Field(default=None, max_length=100)
    edition: str | None = Field(default=None, max_length=100)
    barcode: str | None = Field(default=None, max_length=40)
    work: WorkPick | None = None
    declined: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def _barcode(self):
        if self.barcode:
            try:
                self.barcode = gtin.parse(self.barcode).code
            except gtin.BadBarcode as e:
                raise ValueError(str(e)) from None
        else:
            self.barcode = None
        return self


class WorkLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ref: str = Field(max_length=60, pattern=REF_RE.pattern)


def pick(row: dict | None, fields) -> dict | None:
    return {k: row.get(k) for k in fields} if row else None


def vector_text(v: list[float]) -> str:
    return '[' + ','.join(f'{x:.7g}' for x in v) + ']'


def embeddings_client(settings: Settings, http):
    if settings.embeddings_fake:
        if not settings.supabase_is_local:
            raise RuntimeError('EMBEDDINGS_FAKE is for local Supabase only')
        return FakeEmbeddings()
    key = settings.openai_api_key.get_secret_value()
    return OpenAIEmbeddings(http, key) if key else None


async def catalog_work(svc: Rest, catalog: Catalog, ref: str, user: AuthUser) -> dict:
    """The shared work for a catalog ref, made from the catalog's own facts. HTTPException if it can't be had."""
    try:
        fact = await catalog.work(ref)
    except Unavailable as e:
        raise HTTPException(503, detail={'message': f'{e}; try again, or save without linking'}) from None
    except LookupError as e:
        raise HTTPException(422, detail={'message': str(e)}) from None
    source = ref.split(':', 1)[0]
    ident = ref.split(':', 1)[1]
    return await svc.rpc('work_from_catalog', {
        'p_ref': ref, 'p_title': fact['title'], 'p_year': fact.get('year'), 'p_kind': fact['kind'],
        'p_external_ids': {source: int(ident) if ident.isdigit() else ident}, 'p_created_by': user.id,
    })


@router.post('/releases')
async def create_release(body: ReleaseCreate, request: Request, user: AuthUser = Depends(current_user)):
    """status: created (a new shared release), existing (its barcode already had one: that one, unchanged), similar
    (nothing created; `similar` lists near-identical releases to offer), unavailable (the duplicate check can't run;
    save the item without a shared release)."""
    http, settings = request.app.state.http, get_settings()
    svc = service_db(http)
    work, work_id, new_work, year = None, None, None, None
    if body.work and body.work.ref:
        work = await catalog_work(svc, Catalog(svc, http, settings, user.id), body.work.ref, user)
        work_id, year = work['id'], work.get('year')
    elif body.work and body.work.new:
        new_work = body.work.new.model_dump()
        year = new_work['year']
    fmt = norm_format(body.format) or None

    vector = None
    client = embeddings_client(settings, http)
    try:
        if client is None:
            raise EmbeddingError('The duplicate check is not set up')
        vector = await embed_release_text(svc, client, canonical_text(body.title, fmt, body.edition, year), user.id,
                                          per_user=settings.embed_per_user_daily, per_minute=settings.embed_per_minute,
                                          daily=settings.embed_daily_budget)
    except EmbeddingError as e:
        if not body.barcode:   # without the check a twin could be made; with a barcode the unique index guards
            logger.warning('duplicate check unavailable: %s', e.reason)
            return {'status': 'unavailable', 'release': None, 'similar': [], 'work': pick(work, WORK_FIELDS),
                    'message': f"{e.reason}. Your item can still be saved, without a shared release."}

    out = await svc.rpc('create_user_release', {
        'p_title': body.title, 'p_format': fmt, 'p_edition': body.edition, 'p_barcode': body.barcode,
        'p_embedding': vector_text(vector) if vector else None, 'p_work_id': work_id, 'p_new_work': new_work,
        'p_created_by': user.id, 'p_max_distance': settings.duplicate_max_distance,
        'p_declined': [str(d) for d in body.declined],
    })
    return {'status': out['status'], 'release': pick(out.get('release'), RELEASE_FIELDS), 'work': pick(work, WORK_FIELDS),
            'similar': [{**pick(s, SIMILAR_FIELDS), 'distance': round(s['distance'], 4)} for s in out.get('similar') or []],
            'message': None}


@router.post('/releases/{release_id}/work')
async def link_work(release_id: UUID, body: WorkLink, request: Request, user: AuthUser = Depends(current_user)):
    """Gives a release that has no work yet (a barcode release) the catalog work the owner picked. A release that
    already has a work keeps it: `linked` is false and `work` is the one it has."""
    http, settings = request.app.state.http, get_settings()
    svc = service_db(http)
    work = await catalog_work(svc, Catalog(svc, http, settings, user.id), body.ref, user)
    out = await svc.rpc('link_release_work', {'p_release_id': str(release_id), 'p_work_id': work['id']})
    if not out['linked']:
        rows = await svc.select('works', {'select': ','.join(WORK_FIELDS), 'id': f'eq.{out["work_id"]}'})
        work = rows[0] if rows else None
    return {'linked': out['linked'], 'work': pick(work, WORK_FIELDS)}
