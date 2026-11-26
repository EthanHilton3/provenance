"""UPCitemdb, the barcode catalog, and what we take from its answers.

The request and how its answers are read come from the barcode test's lookup.py (CS-452 Database, 26-11-24): the
free trial endpoint (no key, about 100 lookups a day for the whole app), a 200 with code OK and no items is a miss,
429 and 5xx are never cached. What is new: a short timeout, the Retry-After of a 429, and cleaning the text.

Catalog text is untrusted. It is cut to length, control and invisible formatting characters are dropped (the API
returns stray bytes like a broken (R) sign), and it is only ever stored and shown as data.

`hints()` reads the format, platform and edition words out of that text with the test's keyword patterns. They are
suggestions for the confirmation card, never facts on the shared release: the test found the format in most movie
titles but the edition rarely, so the edition stays a one-tap question.
"""
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx

from .gtin import Barcode

logger = logging.getLogger(__name__)

URL = 'https://api.upcitemdb.com/prod/trial/lookup'
HEADERS = {'User-Agent': 'provenance-catalog', 'Accept': 'application/json'}  # generic: nothing about the user
TIMEOUT_SECONDS = 8
DEFAULT_RETRY_SECONDS = 60
MAX_RETRY_SECONDS = 24 * 3600

# Only what the card uses. The description is dropped: it is long, rarely names the edition, and the less untrusted
# text the shared catalog holds the better.
LIMITS = {'title': 300, 'brand': 200, 'category': 200, 'model': 100}


def clean_text(value, limit: int) -> str | None:
    """Untrusted catalog text -> one plain line of at most `limit` characters, or None."""
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFC', value)
    # Cc control, Cf format (zero-width, bidi overrides), Cs/Co/Cn, and U+FFFD (a byte the API could not decode).
    value = ''.join(' ' if unicodedata.category(c)[0] == 'C' or c == '�' else c for c in value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value[:limit].rstrip() or None


def clean_product(item: dict) -> dict | None:
    """The fields we keep from one UPCitemdb item; None without a usable title."""
    if not isinstance(item, dict):
        return None
    out = {k: clean_text(item.get(k), n) for k, n in LIMITS.items()}
    return out if out['title'] else None


# --- reading the answer ---------------------------------------------------------------------------------------

@dataclass
class UpcResult:
    outcome: Literal['hit', 'miss', 'rate_limited', 'error']
    http_status: int | None = None
    product: dict | None = None
    retry_after: float | None = None      # seconds, for rate_limited
    reason: str = ''
    headers: dict = field(default_factory=dict)


def retry_seconds(headers: httpx.Headers, now: float | None = None) -> float:
    """How long a 429 asks us to wait: Retry-After (seconds or a date), else the daily reset when none are left."""
    now = time.time() if now is None else now
    ra = headers.get('retry-after')
    if ra:
        try:
            secs = float(ra)
        except ValueError:
            try:
                secs = parsedate_to_datetime(ra).timestamp() - now
            except (TypeError, ValueError):
                secs = DEFAULT_RETRY_SECONDS
        return min(max(secs, 1), MAX_RETRY_SECONDS)
    if headers.get('x-ratelimit-remaining') == '0' and (reset := headers.get('x-ratelimit-reset', '')).isdigit():
        return min(max(int(reset) - now, 1), MAX_RETRY_SECONDS)
    return DEFAULT_RETRY_SECONDS


def read_answer(resp: httpx.Response) -> UpcResult:
    status = resp.status_code
    rate = {k: v for k, v in resp.headers.items() if k.lower().startswith(('x-ratelimit', 'retry'))}
    if status == 429:
        return UpcResult('rate_limited', status, retry_after=retry_seconds(resp.headers), reason='rate limited', headers=rate)
    try:
        body = resp.json()
    except ValueError:
        body = None
    code = body.get('code') if isinstance(body, dict) else None
    if status == 200 and code == 'OK':
        items = body.get('items') or []
        product = next((p for p in (clean_product(i) for i in items) if p), None)
        return UpcResult('hit' if product else 'miss', status, product=product, headers=rate)
    if (status == 400 and code == 'INVALID_UPC') or status == 404:
        return UpcResult('miss', status, reason=code or 'not found', headers=rate)  # the catalog's answer: not known
    return UpcResult('error', status, reason=f'HTTP {status} {code or ""}'.strip(), headers=rate)


class UpcItemDb:
    def __init__(self, http: httpx.AsyncClient, url: str = URL, timeout: float = TIMEOUT_SECONDS):
        self._http = http
        self._url = url
        self._timeout = timeout

    async def lookup(self, barcode: Barcode) -> UpcResult:
        """Never raises for a network problem: a timeout or an unreachable API is outcome 'error'."""
        try:
            resp = await self._http.get(self._url, params={'upc': barcode.upc_a or barcode.code}, headers=HEADERS,
                                        timeout=self._timeout)
        except httpx.TimeoutException:
            return UpcResult('error', reason='timeout')
        except httpx.HTTPError as e:
            logger.warning('UPCitemdb unreachable: %s', e)
            return UpcResult('error', reason='unreachable')
        return read_answer(resp)


# --- hints for the card ---------------------------------------------------------------------------------------

# The barcode test's keyword patterns (lookup.py), with "edition" alone and plain "disc" dropped: they say nothing.
FORMAT_RE = re.compile(r'\b(blu-?ray|dvd|4k|uhd|ultra hd|cd|vinyl|lp|cassette|hardcover|paperback)\b', re.I)
PLATFORM_RE = re.compile(r'\b(playstation ?\d?|ps ?[1-5]|xbox( one| 360| series [xs])?|nintendo (switch( 2)?|ds|3ds|wii u|64|gamecube)|switch( 2)?|'
                         r'wii( u)?|game ?cube|game ?boy( advance)?|gba|sega (genesis|saturn|dreamcast)|mega drive|pc game)\b', re.I)
EDITION_RE = re.compile(r"\b(steelbook|collector'?s|limited|special edition|extended|deluxe|ultimate|anniversary|remaster(ed)?|"
                        r"director'?s cut|unrated|criterion|game of the year|goty)\b", re.I)
BRACKETS_RE = re.compile(r'[(\[]([^()\[\]]{2,80})[)\]]')

# Our category templates' spelling of each format and platform (supabase/category_tree.json).
FORMATS = [('4k', '4K UHD'), ('uhd', '4K UHD'), ('ultra hd', '4K UHD'), ('blu', 'Blu-ray'), ('dvd', 'DVD'),
           ('vinyl', 'Vinyl'), ('lp', 'Vinyl'), ('cd', 'CD'), ('cassette', 'Cassette'), ('hardcover', 'Hardcover'),
           ('paperback', 'Paperback')]
PLATFORMS = [('switch 2', 'Switch 2'), ('switch', 'Switch'), ('gamecube', 'GameCube'), ('game cube', 'GameCube'),
             ('wii u', 'Wii U'), ('wii', 'Wii'), ('3ds', 'Nintendo 3DS'), ('nintendo ds', 'Nintendo DS'),
             ('nintendo 64', 'Nintendo 64'), ('game boy advance', 'Game Boy Advance'), ('gameboy advance', 'Game Boy Advance'),
             ('gba', 'Game Boy Advance'), ('game boy', 'Game Boy'), ('gameboy', 'Game Boy'),
             ('playstation 5', 'PS5'), ('ps5', 'PS5'), ('ps 5', 'PS5'), ('playstation 4', 'PS4'), ('ps4', 'PS4'), ('ps 4', 'PS4'),
             ('playstation 3', 'PS3'), ('ps3', 'PS3'), ('playstation 2', 'PS2'), ('ps2', 'PS2'), ('playstation', 'PlayStation'),
             ('xbox series', 'Xbox Series X|S'), ('xbox one', 'Xbox One'), ('xbox 360', 'Xbox 360'), ('xbox', 'Xbox'),
             ('genesis', 'Genesis'), ('mega drive', 'Genesis'), ('saturn', 'Saturn'), ('dreamcast', 'Dreamcast'), ('pc game', 'PC')]
FORMAT_RANK = {'4K UHD': 0, 'Blu-ray': 1, 'DVD': 2}   # "4K UHD + Blu-ray" is a 4K release


def _spelling(found: str, table: list[tuple[str, str]]) -> str:
    low = found.lower()
    return next((ours for key, ours in table if key in low), found)


def hints(product: dict | None, barcode_kind: str = '') -> dict:
    """{kind, format, platform, editions}: guesses from the listing's text, for the card to offer, not to save."""
    p = product or {}
    title = p.get('title') or ''
    text = ' '.join(filter(None, (title, p.get('brand'), p.get('category'), p.get('model'))))
    formats = sorted({_spelling(m.group(0), FORMATS) for m in FORMAT_RE.finditer(text)},
                     key=lambda f: FORMAT_RANK.get(f, 9))
    fmt = formats[0] if formats else None
    plat = PLATFORM_RE.search(text)
    platform = _spelling(plat.group(0), PLATFORMS) if plat else None

    # Edition candidates: a bracketed phrase that names one ("Limited Edition Steelbook"), else the bare words.
    editions: list[str] = []
    for m in BRACKETS_RE.finditer(title):
        phrase = m.group(1).strip()
        if EDITION_RE.search(phrase) and phrase.lower() not in (e.lower() for e in editions):
            editions.append(phrase)
    if not editions:
        for m in EDITION_RE.finditer(title):
            word = m.group(0).title()
            if word.lower() not in (e.lower() for e in editions):
                editions.append(word)

    cat = (p.get('category') or '').lower()
    if fmt in ('4K UHD', 'Blu-ray', 'DVD') or 'dvds & videos' in cat:
        kind = 'movie'
    elif platform or 'video game' in cat:
        kind = 'game'
    elif barcode_kind == 'ISBN-13' or fmt in ('Hardcover', 'Paperback') or 'books' in cat:
        kind = 'book'
    elif fmt in ('Vinyl', 'CD', 'Cassette') or 'music' in cat:
        kind = 'album'
    else:
        kind = None
    return {'kind': kind, 'format': fmt, 'platform': platform, 'editions': editions[:3]}
