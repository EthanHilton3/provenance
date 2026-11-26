"""Barcode lookup (S11) with no network: Supabase and UPCitemdb are one stateful fake, so the tests check what
happens (which source answered, what got cached, what was spent), not the order of HTTP calls.

What the database itself does (ON CONFLICT under concurrency, users unable to write releases, the budget's lock and
caps, check-digit constraints) is proven against the real database in tests/db/test_barcode_lookup.py.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from app import gtin
from app.gtin import BadBarcode, parse
from app.main import app
from app.upc import clean_text, hints, retry_seconds
from test_api import AUTH, USER_A, client  # noqa: F401 (client is a fixture)
from test_intake import JOB, PHOTO

LOTR = '883929704736'                       # The Lord of the Rings 4K, from the barcode test
LOTR_EAN = '0' + LOTR
CONTROLLER = '045496884796'                 # a Switch 2 controller: a real miss in the barcode test
ITEM = {'title': 'The Lord of the Rings: Motion Picture Trilogy (Extended & Theatrical)(4K/UHD)',
        'brand': 'Warner', 'category': 'Media > DVDs & Videos', 'description': 'long text ' * 50, 'model': None}


def upc_ok(*items):
    return 200, {'code': 'OK', 'total': len(items), 'items': list(items)}, {}


class World:
    """Fake Supabase (PostgREST + auth) and fake UPCitemdb, with state: releases, the cache, the call log."""

    def __init__(self, upc=(), budget_error=None):
        self.releases: dict[str, dict] = {}
        self.cache: dict[str, dict] = {}
        self.calls: list[dict] = []          # catalog_calls rows
        self.upc = list(upc)                  # replies: (status, body, headers) or an exception to raise
        self.upc_requests: list[httpx.Request] = []
        self.budget_error = budget_error      # (code, details, message) for begin_catalog_call to raise
        self.rest: list[httpx.Request] = []
        self.rpc_args: dict[str, list] = {}

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == 'api.upcitemdb.com':
            self.upc_requests.append(req)
            r = self.upc.pop(0)
            if isinstance(r, Exception):
                raise r
            return httpx.Response(r[0], json=r[1], headers=r[2])
        if req.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': USER_A, 'email': 'a@example.com'})
        self.rest.append(req)
        path, q = req.url.path.removeprefix('/rest/v1/'), req.url.params
        body = json.loads(req.content) if req.content else None
        if path == 'releases' and req.method == 'GET':
            r = self.releases.get(q['barcode'].removeprefix('eq.'))
            return httpx.Response(200, json=[r] if r else [])
        if path == 'catalog_cache' and req.method == 'GET':
            row = self.cache.get(q['key'].removeprefix('eq.'))
            now = datetime.fromisoformat(q['expires_at'].removeprefix('gt.'))
            return httpx.Response(200, json=[row] if row and datetime.fromisoformat(row['expires_at']) > now else [])
        if path == 'catalog_cache' and req.method == 'POST':
            assert q['on_conflict'] == 'key'
            self.cache[body['key']] = body
            return httpx.Response(201)
        if path == 'catalog_calls' and req.method == 'PATCH':
            self.calls[int(q['id'].removeprefix('eq.')) - 1].update(body)
            return httpx.Response(200, json=[])
        if path == 'rpc/create_intake_jobs' or path == 'intake_jobs':   # as the user, like S10
            assert req.headers['apikey'] == 'anon-test'
            return httpx.Response(200, json=[])
        if path.startswith('rpc/'):
            name = path.removeprefix('rpc/')
            self.rpc_args.setdefault(name, []).append(body)
            assert req.headers['apikey'] == 'service-test', 'catalog writes use the service role'
            if name == 'begin_catalog_call':
                if self.budget_error:
                    code, details, message = self.budget_error
                    return httpx.Response(400, json={'code': code, 'details': details, 'message': message, 'hint': None})
                self.calls.append({'user': body['p_user'], 'outcome': 'pending'})
                return httpx.Response(200, json=len(self.calls))
            if name == 'release_from_catalog':
                code = body['p_barcode']
                created = code not in self.releases
                if created:
                    self.releases[code] = {'id': f'rel-{len(self.releases) + 1}', 'barcode': code, 'title': body['p_title'],
                                           'publisher': body['p_publisher'], 'edition': None, 'format': None,
                                           'release_year': None, 'verified': False, 'attributes': body['p_attributes'],
                                           'created_by': body['p_created_by']}
                return httpx.Response(200, json={**self.releases[code], 'created': created})
        raise AssertionError(f'unexpected call {req.method} {req.url}')


def world(client, **kw) -> World:
    w = World(**kw)
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(w.handler))
    return w


def scan(client, code, **extra):
    return client.post('/api/barcodes/lookup', headers=AUTH, json={'code': code, **extra})


# --- check digits and normalization -------------------------------------------------------------------------

@pytest.mark.parametrize('raw, code, kind', [
    ('036000291452', '0036000291452', 'UPC-A'),
    ('0036000291452', '0036000291452', 'EAN-13'),          # the same product, the same key
    (' 0 36000-29145 2 ', '0036000291452', 'UPC-A'),        # typed with spaces and dashes
    ('4006381333931', '4006381333931', 'EAN-13'),
    ('9780306406157', '9780306406157', 'ISBN-13'),
    ('96385074', '96385074', 'EAN-8'),
    ('01234565', '0012345000065', 'UPC-E'),                 # expands to UPC-A 012345000065
    ('00036000291452', '0036000291452', 'GTIN-14'),
    ('045496900397', '0045496900397', 'UPC-A'),             # IMG_9427 as printed
])
def test_parse_gives_one_canonical_code(raw, code, kind):
    b = parse(raw)
    assert (b.code, b.kind) == (code, kind)


@pytest.mark.parametrize('raw', ['', '   ', '036000291453', '045496600397', '03600029145', 'abc036000291452',
                                 '0360002914521234', '12345', '036000291452x', '０３６０００２９１４５２'])
def test_parse_refuses_bad_codes(raw):
    with pytest.raises(BadBarcode):
        parse(raw)


def test_upc_a_spelling():
    assert parse('0036000291452').upc_a == '036000291452'
    assert parse('4006381333931').upc_a is None


def test_reuses_the_barcode_test_math():
    assert gtin.checksum_valid('036000291452') and gtin.checksum_valid('96385074') and gtin.checksum_valid('01234565')
    assert gtin.upce_to_upca('01234565') == '012345000065'


# --- lookup order --------------------------------------------------------------------------------------------

def test_bad_check_digit_is_422_before_any_lookup(client):
    w = world(client)
    r = scan(client, '045496600397')
    assert r.status_code == 422 and 'check digit' in r.json()['detail']['message']
    assert w.rest == [] and w.upc_requests == []


def test_known_release_answers_with_no_outside_call(client):
    w = world(client)
    w.releases[LOTR_EAN] = {'id': 'rel-1', 'barcode': LOTR_EAN, 'title': ITEM['title'], 'publisher': 'Warner',
                            'attributes': {'catalog': {'category': 'Media > DVDs & Videos'}}}
    r = scan(client, LOTR).json()
    assert r['status'] == 'found' and r['source'] == 'releases' and r['release']['id'] == 'rel-1'
    assert r['hints']['format'] == '4K UHD' and r['hints']['kind'] == 'movie'
    assert w.upc_requests == [] and w.calls == [] and not w.cache
    assert w.rest[0].headers['authorization'] == 'Bearer good'   # releases are read as the user


def test_catalog_hit_makes_a_release_and_caches_it(client):
    w = world(client, upc=[upc_ok(ITEM)])
    r = scan(client, LOTR).json()
    assert r['status'] == 'found' and r['source'] == 'upcitemdb'
    assert r['release']['title'] == ITEM['title'] and r['release']['edition'] is None and r['release']['format'] is None
    assert w.upc_requests[0].url.params['upc'] == LOTR             # asked in its UPC-A spelling
    assert 'provenance' in w.upc_requests[0].headers['user-agent'] and 'ethan' not in str(w.upc_requests[0].headers).lower()
    cached = w.cache[f'upc:{LOTR_EAN}']
    ttl = datetime.fromisoformat(cached['expires_at']) - datetime.fromisoformat(cached['fetched_at'])
    assert cached['response']['found'] is True and ttl == timedelta(days=30)
    assert 'description' not in cached['response']['product']
    assert w.calls == [{'user': USER_A, 'outcome': 'hit', 'http_status': 200, 'retry_after': None}]
    assert w.rpc_args['begin_catalog_call'][0]['p_user'] == USER_A      # from the token, never the body
    assert w.rpc_args['release_from_catalog'][0]['p_created_by'] == USER_A

    again = scan(client, '0' + LOTR).json()                           # EAN-13 spelling: same release, no call
    assert again['source'] == 'releases' and again['release']['id'] == r['release']['id']
    assert len(w.upc_requests) == 1 and len(w.releases) == 1


def test_catalog_miss_is_cached_for_a_week(client):
    w = world(client, upc=[upc_ok()])
    r = scan(client, CONTROLLER).json()
    assert r['status'] == 'not_found' and r['source'] == 'upcitemdb' and r['release'] is None
    cached = w.cache[f'upc:0{CONTROLLER}']
    assert cached['response'] == {'source': 'upcitemdb', 'found': False}
    assert datetime.fromisoformat(cached['expires_at']) - datetime.fromisoformat(cached['fetched_at']) == timedelta(days=7)
    again = scan(client, CONTROLLER).json()
    assert again['status'] == 'not_found' and again['source'] == 'cache'
    assert len(w.upc_requests) == 1 and len(w.calls) == 1 and not w.releases


def test_cached_hit_makes_the_release_without_calling_out(client):
    w = world(client)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    w.cache[f'upc:{LOTR_EAN}'] = {'key': f'upc:{LOTR_EAN}', 'expires_at': future,
                                  'response': {'source': 'upcitemdb', 'found': True, 'product': {'title': 'LOTR 4K', 'brand': 'Warner'}}}
    r = scan(client, LOTR).json()
    assert r['status'] == 'found' and r['source'] == 'cache' and r['release']['title'] == 'LOTR 4K'
    assert w.upc_requests == [] and w.calls == []


def test_expired_cache_asks_the_catalog_again(client):
    w = world(client, upc=[upc_ok(ITEM)])
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    w.cache[f'upc:{LOTR_EAN}'] = {'key': f'upc:{LOTR_EAN}', 'expires_at': past, 'response': {'found': False}}
    assert scan(client, LOTR).json()['source'] == 'upcitemdb'
    assert w.cache[f'upc:{LOTR_EAN}']['response']['found'] is True


# --- failures are never cached as misses ----------------------------------------------------------------------

def test_429_is_not_cached_and_pauses_lookups(client):
    w = world(client, upc=[(429, {'code': 'TOO_FAST'}, {'Retry-After': '45'})])
    r = scan(client, LOTR).json()
    assert r['status'] == 'unavailable' and r['reason'] == 'rate_limited'
    assert not w.cache and not w.releases
    call = w.calls[0]
    assert call['outcome'] == 'rate_limited' and call['http_status'] == 429
    wait = datetime.fromisoformat(call['retry_after']) - datetime.now(timezone.utc)
    assert timedelta(seconds=40) < wait <= timedelta(seconds=45)


@pytest.mark.parametrize('reply, http_status', [
    (httpx.ReadTimeout('slow'), None),
    (httpx.ConnectError('down'), None),
    ((500, {'code': 'INTERNAL'}, {}), 500),
    ((200, ['not', 'the', 'shape'], {}), 200),
])
def test_errors_are_unavailable_and_not_cached(client, reply, http_status):
    w = world(client, upc=[reply])
    r = scan(client, LOTR).json()
    assert r['status'] == 'unavailable' and r['reason'] == 'catalog_error'
    assert not w.cache and not w.releases
    assert w.calls[0]['outcome'] == 'error' and w.calls[0]['http_status'] == http_status


@pytest.mark.parametrize('details, code', [('daily', 'PT429'), ('user', 'PT429'), ('cooldown', 'PT503'), ('minute', 'PT503')])
def test_spent_budget_skips_the_catalog(client, details, code):
    w = world(client, budget_error=(code, details, 'Barcode lookups are used up for today'))
    r = scan(client, LOTR).json()
    assert r['status'] == 'unavailable' and r['reason'] == details and r['message']
    assert w.upc_requests == [] and not w.cache


def test_lookup_takes_only_a_code(client):
    w = world(client)
    assert scan(client, LOTR, user_id='someone-else').status_code == 422
    assert client.post('/api/barcodes/lookup', headers=AUTH, json={'code': '1' * 41}).status_code == 422
    assert w.rest == []


def test_no_route_writes_a_release(client):
    world(client)
    for method in ('PUT', 'PATCH', 'DELETE'):
        assert client.request(method, '/api/barcodes/lookup', headers=AUTH).status_code == 405
        assert client.request(method, '/api/releases/rel-1', headers=AUTH).status_code == 404


# --- untrusted catalog text ------------------------------------------------------------------------------------

def test_catalog_text_is_cleaned_before_it_is_stored(client):
    nasty = {'title': 'Nintendo� Zelda‮​\x00 ' + 'x' * 500, 'brand': '  Nin\ntendo  ',
             'category': None, 'model': 12}
    w = world(client, upc=[upc_ok({'title': '   '}, nasty)])               # the first item has no usable title
    r = scan(client, LOTR).json()
    title = r['release']['title']
    assert title.startswith('Nintendo Zelda x') and len(title) <= 300
    assert not any(c in title for c in '�‮​\x00')
    assert w.releases[LOTR_EAN]['publisher'] == 'Nin tendo'
    assert w.cache[f'upc:{LOTR_EAN}']['response']['product']['model'] is None


def test_clean_text():
    assert clean_text('  a\tb\r\nc  ', 10) == 'a b c'
    assert clean_text('abcdef', 3) == 'abc' and clean_text('', 5) is None and clean_text(5, 5) is None


# --- hints from the barcode test's real titles -----------------------------------------------------------------

@pytest.mark.parametrize('product, expected', [
    (ITEM, {'kind': 'movie', 'format': '4K UHD', 'platform': None, 'editions': ['Extended & Theatrical']}),
    ({'title': 'Nausicaa Of The Valley Of The Wind (Limited Edition Steelbook) (Blu-ray + DVD)', 'brand': 'SDS',
      'category': 'Media > DVDs & Videos'},
     {'kind': 'movie', 'format': 'Blu-ray', 'platform': None, 'editions': ['Limited Edition Steelbook']}),
    ({'title': 'Dragon Ball Z: Seasons 1-9 Collection (Amazon Exclusive) [Blu-ray] (B075KZBHD6)', 'brand': 'Funimation',
      'category': 'Electronics > Video > Video Players & Recorders > DVD & Blu-ray Players'},
     {'kind': 'movie', 'format': 'Blu-ray', 'platform': None, 'editions': []}),
    ({'title': 'Restored Super Smash Bros Melee', 'brand': 'Nintendo GameCube', 'category': 'Software > Video Game Software'},
     {'kind': 'game', 'format': None, 'platform': 'GameCube', 'editions': []}),
    ({'title': 'Nintendo The Legend of Zelda: Ocarina of Time - Nintendo Switch 2', 'brand': 'Nintendo', 'category': None},
     {'kind': 'game', 'format': None, 'platform': 'Switch 2', 'editions': []}),
    ({'title': 'The Ultimate Aang & Korra Blu-ray Collection', 'brand': 'Paramount', 'category': 'Media > DVDs & Videos'},
     {'kind': 'movie', 'format': 'Blu-ray', 'platform': None, 'editions': ['Ultimate']}),
    ({'title': 'Some Mug', 'brand': None, 'category': None}, {'kind': None, 'format': None, 'platform': None, 'editions': []}),
])
def test_hints(product, expected):
    assert hints(product) == expected


def test_retry_seconds():
    now = time.time()
    assert retry_seconds(httpx.Headers({'retry-after': '12'}), now) == 12
    date = format_datetime(datetime.fromtimestamp(now + 90, timezone.utc), usegmt=True)
    assert 85 <= retry_seconds(httpx.Headers({'retry-after': date}), now) <= 91
    assert retry_seconds(httpx.Headers({'x-ratelimit-remaining': '0', 'x-ratelimit-reset': str(int(now) + 600)}), now) == pytest.approx(600, abs=1)
    assert retry_seconds(httpx.Headers({'retry-after': '99999999'}), now) == 24 * 3600
    assert retry_seconds(httpx.Headers({}), now) == 60


# --- a barcode on an intake job --------------------------------------------------------------------------------

def test_intake_job_takes_a_canonical_barcode(client):
    w = world(client)
    r = client.post('/api/intake/jobs', headers=AUTH, json={'photo_ids': [PHOTO], 'mode': 'single', 'barcode': LOTR})
    assert r.status_code == 201, r.text
    sent = json.loads(next(c for c in w.rest if c.url.path.endswith('/rpc/create_intake_jobs')).content)
    assert sent['p_barcode'] == LOTR_EAN


@pytest.mark.parametrize('body', [
    {'photo_ids': [PHOTO], 'mode': 'single', 'barcode': '045496600397'},
    {'photo_ids': [PHOTO], 'mode': 'group', 'barcode': LOTR},
    {'photo_ids': [PHOTO, JOB], 'mode': 'single', 'barcode': LOTR},
])
def test_intake_barcode_rules(client, body):
    w = world(client)
    assert client.post('/api/intake/jobs', headers=AUTH, json=body).status_code == 422
    assert w.rest == []
