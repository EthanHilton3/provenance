"""Embeddings for the duplicate-release check (S12): OpenAI text-embedding-3-small at 512 dimensions, the size of
releases.embedding (see the initial schema for why 512).

Only releases without a barcode need the check (a barcode has its unique index), and only the release's catalog
facts are embedded: `canonical_text()` of title, format, edition and year. Nothing private (notes, photos, owner)
is ever sent.

The API calls this when the owner saves, not the worker: the owner edits format and edition after the AI, and the
check must see what they approved. Vectors are cached in catalog_cache by a hash of the text, so asking again after
"no, mine is different" costs nothing. Calls go through begin_catalog_call() (provider 'openai_embed') for a per-user
cap. The key is sent as a header only and never logged.

`FakeEmbeddings` (tests and local walks, no network): a hashed bag of words and word pairs, so texts that share
words are close. It is only for exercising the flow; the threshold comes from real vectors
(scripts/duplicate_threshold.py).
"""
import hashlib
import logging
import math
import re
from datetime import datetime, timedelta, timezone

import httpx

from .db import DbError, Rest
from .upc import FORMATS, PLATFORMS

logger = logging.getLogger(__name__)

URL = 'https://api.openai.com/v1/embeddings'
MODEL = 'text-embedding-3-small'
DIMENSIONS = 512
PRICE_PER_M_TOKENS = 0.02          # USD, text-embedding-3-small
TIMEOUT_SECONDS = 10
CACHE_TTL = timedelta(days=180)
TEXT_VERSION = 'v1'                 # bump if canonical_text() changes: cached vectors and stored ones go stale

# Our spelling of formats and platforms (the category templates'), plus the book words the barcode table lacks.
_SPELLINGS = FORMATS + [('hardback', 'Hardcover'), ('softcover', 'Paperback'), ('mass market', 'Paperback')] + PLATFORMS


class EmbeddingError(Exception):
    """The embedding could not be made. `reason` is safe to show."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def norm_format(value: str | None) -> str:
    """"4K Ultra HD" -> "4K UHD", "Nintendo Switch" -> "Switch", "hardback" -> "Hardcover"; unknown words as typed."""
    text = ' '.join((value or '').split())
    if not text:
        return ''
    low = text.lower()
    return next((ours for key, ours in _SPELLINGS if key in low), text)


def norm_edition(value: str | None) -> str:
    text = ' '.join((value or '').split())
    return 'Standard' if not text or text.lower() in ('standard', 'standard edition', 'regular', 'normal') else text


def canonical_text(title: str, format: str | None = None, edition: str | None = None, year: int | None = None) -> str:
    """The one line embedded for a release. Blank edition = Standard (the same release), blank format = unknown."""
    parts = [f'title: {" ".join(title.split())}', f'format: {norm_format(format) or "unknown"}',
             f'edition: {norm_edition(edition)}', f'year: {year or "unknown"}']
    return ' | '.join(parts)


def cost_usd(tokens: int) -> float:
    return tokens * PRICE_PER_M_TOKENS / 1_000_000


class OpenAIEmbeddings:
    def __init__(self, http: httpx.AsyncClient, api_key: str, url: str = URL):
        self._http, self._key, self._url = http, api_key, url

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        """(vectors in input order, usage). Raises EmbeddingError; never includes the key in it."""
        body = {'model': MODEL, 'input': texts, 'dimensions': DIMENSIONS, 'encoding_format': 'float'}
        try:
            resp = await self._http.post(self._url, json=body, headers={'Authorization': f'Bearer {self._key}'},
                                         timeout=TIMEOUT_SECONDS)
        except httpx.TimeoutException:
            raise EmbeddingError('The duplicate check timed out') from None
        except httpx.HTTPError:
            raise EmbeddingError('Could not reach the duplicate check service') from None
        if resp.status_code >= 400:
            logger.warning('OpenAI embeddings HTTP %s', resp.status_code)   # the body can quote the key: not logged
            raise EmbeddingError(f'The duplicate check service answered HTTP {resp.status_code}')
        try:
            data = resp.json()
            vectors = [d['embedding'] for d in sorted(data['data'], key=lambda d: d['index'])]
            tokens = int((data.get('usage') or {}).get('total_tokens') or 0)
        except (ValueError, KeyError, TypeError):
            raise EmbeddingError('The duplicate check service sent an unreadable reply') from None
        if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
            raise EmbeddingError('The duplicate check service sent vectors of the wrong size')
        return vectors, {'model': MODEL, 'tokens': tokens, 'cost_usd': round(cost_usd(tokens), 8)}


class FakeEmbeddings:
    """Deterministic, no network: hashed words and word pairs, L2-normalized."""

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        return [fake_vector(t) for t in texts], {'model': 'fake', 'tokens': 0, 'cost_usd': 0.0}


def fake_vector(text: str) -> list[float]:
    words = re.findall(r'[a-z0-9]+', text.lower())
    v = [0.0] * DIMENSIONS
    for tok in words + [f'{a} {b}' for a, b in zip(words, words[1:])]:
        h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4], 'big')
        v[h % DIMENSIONS] += 1.0 if h & 1 << 31 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cache_key(text: str) -> str:
    return f'embed:{MODEL}:{DIMENSIONS}:{TEXT_VERSION}:{hashlib.sha256(text.encode()).hexdigest()}'


async def embed_release_text(svc: Rest, client, text: str, user_id: str, *, per_user: int, per_minute: int,
                             daily: int) -> list[float]:
    """One release's vector: from the cache, else from `client` under the per-user cap. Raises EmbeddingError."""
    key = cache_key(text)
    now = datetime.now(timezone.utc)
    rows = await svc.select('catalog_cache', {'select': 'response', 'key': f'eq.{key}', 'expires_at': f'gt.{now.isoformat()}'})
    if rows and isinstance((rows[0]['response'] or {}).get('vector'), list):
        return rows[0]['response']['vector']
    try:
        call_id = await svc.rpc('begin_catalog_call', {'p_provider': 'openai_embed', 'p_user': user_id, 'p_daily': daily,
                                                       'p_per_user': per_user, 'p_per_minute': per_minute})
    except DbError as e:
        info = e.body if isinstance(e.body, dict) else {}
        if info.get('code') in ('PT429', 'PT503'):
            raise EmbeddingError('Too many duplicate checks right now; try again shortly') from None
        raise
    try:
        vectors, usage = await client.embed([text])
    except EmbeddingError:
        await _finish(svc, call_id, 'error')
        raise
    await _finish(svc, call_id, 'hit')
    logger.info('embedding: %s tokens, $%.8f', usage['tokens'], usage['cost_usd'])
    try:
        await svc.upsert('catalog_cache', {'key': key, 'response': {'vector': vectors[0], 'model': MODEL},
                                           'fetched_at': now.isoformat(), 'expires_at': (now + CACHE_TTL).isoformat()},
                         on_conflict='key')
    except DbError as e:
        logger.error('Could not cache an embedding: %s', e)
    return vectors[0]


async def _finish(svc: Rest, call_id: int, outcome: str) -> None:
    try:
        await svc.update('catalog_calls', {'id': f'eq.{call_id}'}, {'outcome': outcome})
    except DbError as e:
        logger.error('Could not record catalog call %s: %s', call_id, e)
