"""The catalog service (S12): a clean title plus kind and year hints -> ranked candidate works.

TMDB answers for films and shows, Open Library for books (by ISBN and by title). Video games stay AI and barcode only
(no IGDB yet), and every other category skips the catalog: `search()` returns status 'skipped' for them.

Order, stopping at the first step that finds a plausible title:
1. ISBN (books only), when there is one: Open Library's work for that edition.
2. The title as given, with the year hint as a filter where the catalog takes one.
3. The title loosened: bracketed text, format, platform and edition words and a year removed ("Princess Mononoke
   (1997) [Blu-ray] Steelbook" -> "Princess Mononoke"), without the year filter.
4. Nothing: the card offers "none of these", which can create a user work (create_user_release()).

Ranking: title likeness first (exact, after normalizing case, punctuation and a leading "The"), then the year hint.
`strength` is 'strong' only for an exact title that the year confirms, or the only exact title when there is no year.
Everything else is 'weak', and the card then preselects nothing: a weak match is never linked silently (two shows are
both called "Avatar: The Last Airbender").

Each provider call: the cache first (catalog_cache; results 30 days, empty answers 7; TMDB allows caching up to 6
months), then the shared budget (begin_catalog_call(): per user, per minute, and a pause as long as a 429 asks), then
the request with a short timeout and one retry after a short backoff on a timeout or a 5xx. A 429 or an error is never
cached. If a catalog cannot be asked, `search()` says 'unavailable' and the card still saves.

Keys and privacy: the TMDB v3 key goes only in the query string of requests to TMDB. httpx's request log (which would
print that URL) is held at WARNING, and nothing here logs a URL, a response body or an exception's text. Open Library
gets a generic User-Agent with nothing about the user. Catalog text is untrusted: cleaned, cut to length, shown as data.
"""
import asyncio
import logging
import random
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthUser, current_user
from .config import Settings, get_settings
from .db import DbError, Rest, service_db
from .upc import EDITION_RE, FORMAT_RE, PLATFORM_RE, clean_text, retry_seconds

logging.getLogger('httpx').setLevel(logging.WARNING)   # its INFO line prints request URLs, TMDB's key included
logger = logging.getLogger(__name__)
router = APIRouter()

HEADERS = {'User-Agent': 'provenance-catalog/0.1', 'Accept': 'application/json'}   # generic: nothing about the user
TIMEOUT_SECONDS = 6
OL_TIMEOUT_SECONDS = 10   # Open Library answered in 5.3 s in the S12 smoke test; TMDB in well under 1 s
BACKOFF_SECONDS = 0.5
HIT_TTL = timedelta(days=30)
MISS_TTL = timedelta(days=7)
MAX_CANDIDATES = 6
REF_RE = re.compile(r'^(tmdb_movie|tmdb_tv|ol_work):[A-Za-z0-9]{1,40}$')

Kind = Literal['movie', 'tv', 'screen', 'book', 'game', 'other']   # screen: a film or a show, not known which
Step = Literal['isbn', 'exact', 'loose', 'none']


@dataclass
class Candidate:
    ref: str                 # 'tmdb_movie:128', 'tmdb_tv:246', 'ol_work:OL27482W'
    title: str
    year: int | None
    kind: Literal['movie', 'tv', 'book']
    source: Literal['tmdb', 'open_library']
    detail: str | None = None   # original title, or authors
    popularity: float = 0.0
    score: float = 0.0
    exact: bool = False


@dataclass
class Answer:
    outcome: Literal['hit', 'miss', 'rate_limited', 'error']
    items: list[dict] = field(default_factory=list)
    retry_after: float | None = None
    http_status: int | None = None


class Unavailable(Exception):
    """A catalog could not be asked (budget, rate limit, timeout, error). Nothing was cached."""


# --- titles -------------------------------------------------------------------------------------------------------

def norm_title(text: str | None) -> str:
    t = unicodedata.normalize('NFKD', text or '')
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower().replace('&', ' and ')
    t = re.sub(r'[^a-z0-9]+', ' ', t).strip()
    return re.sub(r'^the ', '', t)


YEAR_RE = re.compile(r'\(\s*((?:1[89]|20)\d\d)\s*\)')
EXTRA_WORDS_RE = re.compile(r'\b(edition|steel ?book|box ?set|digital( copy| code)?|blu-?ray|combo pack|\+)\b', re.I)


def split_year(title: str) -> tuple[str, int | None]:
    """'Princess Mononoke (1997)' -> ('Princess Mononoke', 1997): the feasibility test's model wrote search text so."""
    m = YEAR_RE.search(title or '')
    if not m:
        return (title or '').strip(), None
    return (title[:m.start()] + title[m.end():]).strip(' -:'), int(m.group(1))


def loosen(title: str) -> str:
    t = re.sub(r'[(\[][^()\[\]]*[)\]]', ' ', title or '')
    for pattern in (FORMAT_RE, PLATFORM_RE, EDITION_RE, EXTRA_WORDS_RE):
        t = pattern.sub(' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip(' -:/,')


def _year(date: str | None) -> int | None:
    m = re.match(r'^\s*(\d{4})', date or '')
    return int(m.group(1)) if m else None


def rank(cands: list[Candidate], query: str, year: int | None) -> list[Candidate]:
    q = norm_title(query)
    qwords = set(q.split())
    for c in cands:
        names = [norm_title(c.title)] + ([norm_title(c.detail)] if c.source == 'tmdb' and c.detail else [])
        c.exact = q in names
        likeness = 1.0 if c.exact else max(
            (len(qwords & set(n.split())) / len(qwords | set(n.split())) if n else 0.0) for n in names)
        fit = 0.5 if year is None or c.year is None else 1.0 if c.year == year else 0.6 if abs(c.year - year) == 1 else 0.0
        c.score = round(0.7 * likeness + 0.3 * fit, 3)
    return sorted(cands, key=lambda c: (-c.score, -c.popularity))


def strength(cands: list[Candidate], year: int | None) -> Literal['strong', 'weak'] | None:
    if not cands:
        return None
    top = cands[0]
    exact = [c for c in cands if c.exact]
    if top.exact and year is not None and top.year == year and sum(1 for c in exact if c.year == year) == 1:
        return 'strong'
    if top.exact and year is None and len(exact) == 1:
        return 'strong'
    return 'weak'


def plausible(cands: list[Candidate]) -> bool:
    return any(c.score >= 0.5 for c in cands)


# --- providers ------------------------------------------------------------------------------------------------------

async def get_json(http: httpx.AsyncClient, url: str, params: dict, *, retries: int = 1,
                   backoff: float | None = None, timeout: float = TIMEOUT_SECONDS) -> tuple[int | None, dict | None, httpx.Headers | None]:
    """(status, body, headers); status None when no answer came. One retry after a timeout, network error or 5xx."""
    backoff = BACKOFF_SECONDS if backoff is None else backoff
    for attempt in range(retries + 1):
        try:
            resp = await http.get(url, params=params, headers=HEADERS, timeout=timeout)
        except httpx.HTTPError as e:
            status, body, headers, why = None, None, None, type(e).__name__
        else:
            try:
                body = resp.json()
            except ValueError:
                body = None
            status, headers, why = resp.status_code, resp.headers, f'HTTP {resp.status_code}'
            if status < 500:
                return status, body, headers
        if attempt < retries:
            logger.info('catalog request failed (%s); retrying', why)
            await asyncio.sleep(backoff * (2 ** attempt) * (1 + random.random() / 2))
    return status, body, headers


def answer_of(status: int | None, body, headers, items_of) -> Answer:
    if status == 429:
        return Answer('rate_limited', retry_after=retry_seconds(headers or httpx.Headers()), http_status=429)
    if status == 404:
        return Answer('miss', http_status=404)
    if status != 200 or not isinstance(body, dict):
        return Answer('error', http_status=status)
    items = items_of(body)
    return Answer('hit' if items else 'miss', items, http_status=200)


def _tmdb_item(kind: str, r: dict) -> dict | None:
    if not isinstance(r, dict) or not isinstance(r.get('id'), int):
        return None
    title = clean_text(r.get('title') if kind == 'movie' else r.get('name'), 300)
    if not title:
        return None
    original = clean_text(r.get('original_title') if kind == 'movie' else r.get('original_name'), 300)
    return {'ref': f'tmdb_{kind}:{r["id"]}', 'title': title, 'kind': kind, 'source': 'tmdb',
            'year': _year(r.get('release_date') if kind == 'movie' else r.get('first_air_date')),
            'detail': original if original and original != title else None,
            'popularity': float(r.get('popularity') or 0)}


def _ol_item(doc: dict) -> dict | None:
    key = (doc or {}).get('key') or ''
    m = re.fullmatch(r'/works/(OL[0-9]+W)', key)
    title = clean_text(doc.get('title'), 300)
    if not m or not title:
        return None
    authors = [a for a in (clean_text(x, 100) for x in (doc.get('author_name') or [])[:3]) if a]
    year = doc.get('first_publish_year') if isinstance(doc.get('first_publish_year'), int) else _year(doc.get('first_publish_date'))
    return {'ref': f'ol_work:{m.group(1)}', 'title': title, 'kind': 'book', 'source': 'open_library', 'year': year,
            'detail': ', '.join(authors) or None, 'popularity': float(doc.get('edition_count') or 0)}


class Tmdb:
    def __init__(self, http: httpx.AsyncClient, api_key: str, base: str):
        self.http, self._key, self.base = http, api_key, base.rstrip('/')

    async def search(self, kind: str, query: str, year: int | None) -> Answer:
        params = {'api_key': self._key, 'query': query, 'include_adult': 'false', 'language': 'en-US'}
        if year:
            params['year' if kind == 'movie' else 'first_air_date_year'] = str(year)
        st, body, h = await get_json(self.http, f'{self.base}/search/{kind}', params)
        return answer_of(st, body, h, lambda b: [i for i in (_tmdb_item(kind, r) for r in (b.get('results') or [])[:10]) if i])

    async def details(self, kind: str, tmdb_id: str) -> Answer:
        st, body, h = await get_json(self.http, f'{self.base}/{kind}/{tmdb_id}', {'api_key': self._key, 'language': 'en-US'})
        return answer_of(st, body, h, lambda b: [i for i in [_tmdb_item(kind, b)] if i])


class OpenLibrary:
    FIELDS = 'key,title,author_name,first_publish_year,edition_count'

    def __init__(self, http: httpx.AsyncClient, base: str):
        self.http, self.base = http, base.rstrip('/')

    async def by_isbn(self, isbn: str) -> Answer:
        st, body, h = await get_json(self.http, f'{self.base}/search.json', {'q': f'isbn:{isbn}', 'fields': self.FIELDS, 'limit': '3'},
                                     timeout=OL_TIMEOUT_SECONDS)
        return answer_of(st, body, h, lambda b: [i for i in (_ol_item(d) for d in (b.get('docs') or [])) if i])

    async def search(self, title: str) -> Answer:
        st, body, h = await get_json(self.http, f'{self.base}/search.json', {'title': title, 'fields': self.FIELDS, 'limit': '8'},
                                     timeout=OL_TIMEOUT_SECONDS)
        return answer_of(st, body, h, lambda b: [i for i in (_ol_item(d) for d in (b.get('docs') or [])) if i])

    async def work(self, key: str) -> Answer:
        st, body, h = await get_json(self.http, f'{self.base}/works/{key}.json', {}, timeout=OL_TIMEOUT_SECONDS)
        return answer_of(st, body, h, lambda b: [i for i in [_ol_item({**b, 'key': f'/works/{key}'})] if i])


# --- the service ----------------------------------------------------------------------------------------------------

class Catalog:
    def __init__(self, svc: Rest, http: httpx.AsyncClient, settings: Settings, user_id: str):
        self.svc, self.settings, self.user_id = svc, settings, user_id
        self.tmdb = Tmdb(http, settings.tmdb_api_key.get_secret_value(), settings.tmdb_url)
        self.ol = OpenLibrary(http, settings.openlibrary_url)

    async def _cached(self, key: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        rows = await self.svc.select('catalog_cache', {'select': 'response', 'key': f'eq.{key}', 'expires_at': f'gt.{now}'})
        return rows[0]['response'] if rows else None

    async def _store(self, key: str, value: dict, ttl: timedelta) -> None:
        now = datetime.now(timezone.utc)
        try:
            await self.svc.upsert('catalog_cache', {'key': key, 'response': value, 'fetched_at': now.isoformat(),
                                                    'expires_at': (now + ttl).isoformat()}, on_conflict='key')
        except DbError as e:   # the answer still stands; the next search just asks again
            logger.error('Could not cache %s: %s', key.split(':')[0], e.status)

    async def _ask(self, provider: str, key: str, call) -> list[dict]:
        """Cache, budget, call, record, cache. Raises Unavailable; never caches a 429 or an error."""
        cached = await self._cached(key)
        if cached is not None:
            return cached.get('items') or []
        s = self.settings
        limits = {'tmdb': (s.tmdb_daily_budget, s.tmdb_per_user_daily, s.tmdb_per_minute),
                  'openlibrary': (s.openlibrary_daily_budget, s.openlibrary_per_user_daily, s.openlibrary_per_minute)}[provider]
        try:
            call_id = await self.svc.rpc('begin_catalog_call', {'p_provider': provider, 'p_user': self.user_id,
                                                                'p_daily': limits[0], 'p_per_user': limits[1], 'p_per_minute': limits[2]})
        except DbError as e:
            info = e.body if isinstance(e.body, dict) else {}
            if info.get('code') in ('PT429', 'PT503'):
                raise Unavailable(info.get('message') or 'The catalog is busy') from None
            raise
        ans: Answer = await call()
        values = {'http_status': ans.http_status, 'outcome': ans.outcome, 'retry_after': None}
        if ans.outcome == 'rate_limited':
            values['retry_after'] = (datetime.now(timezone.utc) + timedelta(seconds=ans.retry_after or 60)).isoformat()
            logger.warning('%s rate limited us for %.0f s', provider, ans.retry_after or 60)
        elif ans.outcome == 'error':
            logger.warning('%s did not answer (HTTP %s)', provider, ans.http_status)
        try:
            await self.svc.update('catalog_calls', {'id': f'eq.{call_id}'}, values)
        except DbError as e:
            logger.error('Could not record catalog call %s: %s', call_id, e.status)
        if ans.outcome in ('rate_limited', 'error'):
            raise Unavailable('The catalog is busy' if ans.outcome == 'rate_limited' else "The catalog didn't answer")
        await self._store(key, {'items': ans.items}, HIT_TTL if ans.items else MISS_TTL)
        for item in ans.items:   # each candidate by its ref, so linking reads the catalog's facts, not the client's
            await self._store(f'work:{item["ref"]}', item, HIT_TTL)
        return ans.items

    async def _step(self, kinds: list[str], title: str, year: int | None) -> tuple[list[Candidate], int]:
        """Candidates from every catalog for these kinds, and how many of those catalogs could not be asked."""
        q = title.lower()[:200]
        out, failed = [], 0
        for kind in kinds:
            try:
                if kind == 'book':
                    items = await self._ask('openlibrary', f'ol:search:{q}', lambda: self.ol.search(title))
                else:
                    items = await self._ask('tmdb', f'tmdb:{kind}:search:{q}:{year or ""}',
                                            lambda k=kind: self.tmdb.search(k, title, year))
            except Unavailable:
                failed += 1
                continue
            out += [Candidate(**i) for i in items]
        return out, failed

    async def search(self, title: str, kind: Kind | None, year: int | None = None, isbn: str | None = None) -> dict:
        if kind not in ('movie', 'tv', 'screen', 'book'):
            return result('skipped', 'none', [], None)
        title, year_in_title = split_year(clean_text(title, 300) or '')
        year = year or year_in_title
        kinds = ['book'] if kind == 'book' else ['movie', 'tv'] if kind == 'screen' else [kind]
        unavailable = 0
        if kind == 'book' and isbn:
            try:
                items = await self._ask('openlibrary', f'ol:isbn:{isbn}', lambda: self.ol.by_isbn(isbn))
            except Unavailable:
                unavailable += 1
            else:
                if items:   # the ISBN names the edition: its work is the answer
                    cands = [Candidate(**i, score=1.0, exact=True) for i in items]
                    return result('ok', 'isbn', cands, 'strong' if len(cands) == 1 else 'weak')
        if not title:
            return result('unavailable' if unavailable else 'ok', 'none', [], None)

        steps = [('exact', title, year)]
        loose = loosen(title)
        if loose and norm_title(loose) != norm_title(title):
            steps.append(('loose', loose, None))
        elif year:
            steps.append(('loose', title, None))
        seen = None   # the first unlikely answer: shown as weak choices if no step does better
        for step, query, y in steps:
            cands, failed = await self._step(kinds, query, y)
            unavailable += failed
            cands = rank(cands, query, year)
            if plausible(cands):
                return result('ok', step, cands, strength(cands, year))
            seen = seen or (cands and (step, cands))
            if failed == len(kinds):   # nobody answered: a looser query won't help
                break
        if seen:
            return result('ok', seen[0], seen[1], 'weak')
        return result('unavailable' if unavailable else 'ok', 'none', [], None)

    async def work(self, ref: str) -> dict:
        """A candidate's catalog facts by its ref: the cache, else the catalog. Raises Unavailable or LookupError."""
        if not REF_RE.match(ref):
            raise LookupError('Not a catalog reference')
        cached = await self._cached(f'work:{ref}')
        if cached:
            return cached
        source, ident = ref.split(':', 1)
        if source == 'ol_work':
            items = await self._ask('openlibrary', f'work:{ref}:fetch', lambda: self.ol.work(ident))
        else:
            kind = source.removeprefix('tmdb_')
            items = await self._ask('tmdb', f'work:{ref}:fetch', lambda: self.tmdb.details(kind, ident))
        if not items:
            raise LookupError('That catalog entry no longer exists')
        return items[0]


def result(status: str, step: Step, cands: list[Candidate], strong: str | None) -> dict:
    cands = cands[:MAX_CANDIDATES]
    return {'status': status, 'step': step, 'strength': strong,
            'candidates': [{k: v for k, v in asdict(c).items() if k not in ('popularity',)} for c in cands],
            'sources': sorted({c.source for c in cands}),
            'message': "The catalog can't be reached right now; you can still save" if status == 'unavailable' else None}


def catalog_for(request: Request, user: AuthUser = Depends(current_user)) -> Catalog:
    http = request.app.state.http
    return Catalog(service_db(http), http, get_settings(), user.id)


class Search(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='', max_length=300)
    kind: Kind | None = None
    year: int | None = Field(default=None, ge=1000, le=3000)
    isbn: str | None = Field(default=None, pattern=r'^97[89][0-9]{10}$')


@router.post('/catalog/search')
async def search(body: Search, catalog: Catalog = Depends(catalog_for)):
    """status: ok (with candidates, maybe none), skipped (this kind has no catalog), unavailable (can't ask now).
    strength: strong (preselect it) or weak (show, preselect nothing). step: which fallback answered."""
    return await catalog.search(body.title, body.kind, body.year, body.isbn)
