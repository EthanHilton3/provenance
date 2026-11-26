"""Catalog service, user-created releases and the duplicate check (S12), with no network: Supabase, TMDB, Open Library
and OpenAI's embeddings are one stateful fake, so the tests check what happens (which catalog was asked in which order,
what got cached, what was shared), not the exact HTTP.

What the database itself does (one work per catalog entry and one release when two people create at once, the lock
and re-check, hidden created_by, users unable to write) is proven against the real database in tests/db/test_catalog.py.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import catalog as catalog_module
from app.catalog import loosen, norm_title, split_year
from app.config import get_settings
from app.embeddings import canonical_text, fake_vector, norm_format
from app.main import app
from test_api import AUTH, USER_A, client  # noqa: F401 (client is a fixture)

TMDB_KEY = 'tmdbtestkey0000000000000000000000'
MONONOKE = {'id': 128, 'title': 'Princess Mononoke', 'original_title': 'もののけ姫', 'release_date': '1997-07-12', 'popularity': 23.1}
AVATAR_2005 = {'id': 246, 'name': 'Avatar: The Last Airbender', 'original_name': 'Avatar: The Last Airbender',
               'first_air_date': '2005-02-21', 'popularity': 34.9}
AVATAR_2024 = {**AVATAR_2005, 'id': 82452, 'first_air_date': '2024-02-22', 'popularity': 38.9}
HOBBIT = {'key': '/works/OL27482W', 'title': 'The Hobbit', 'author_name': ['J.R.R. Tolkien'], 'first_publish_year': 1937,
          'edition_count': 482}


def tmdb(*results, status=200, headers=None):
    return status, {'page': 1, 'results': list(results)}, headers or {}


def ol(*docs):
    return 200, {'numFound': len(docs), 'docs': list(docs)}, {}


class World:
    """Fake Supabase (auth, catalog_cache, catalog_calls, the S12 functions) and fake TMDB, Open Library, OpenAI."""

    def __init__(self, tmdb=(), ol=(), openai=(), budget_error=None, create=None):
        self.tmdb, self.ol, self.openai = list(tmdb), list(ol), list(openai)
        self.requests: list[httpx.Request] = []          # to the outside catalogs, in order
        self.cache: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.rpc_args: dict[str, list] = {}
        self.budget_error = budget_error
        self.create = create or {'status': 'created', 'release': {'id': 'rel-new', 'title': 'x', 'barcode': None},
                                 'similar': []}
        self.works: dict[str, dict] = {}

    def _outside(self, queue, req):
        self.requests.append(req)
        assert queue, f'unexpected call {req.url}'
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r[0], json=r[1], headers=r[2])

    def handler(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == 'api.themoviedb.org':
            return self._outside(self.tmdb, req)
        if host == 'openlibrary.org':
            return self._outside(self.ol, req)
        if host == 'api.openai.com':
            return self._outside(self.openai, req)
        if req.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': USER_A, 'email': 'a@example.com'})
        path, q = req.url.path.removeprefix('/rest/v1/'), req.url.params
        body = json.loads(req.content) if req.content else None
        assert req.headers['apikey'] == 'service-test', 'catalog work uses the service role'
        if path == 'catalog_cache' and req.method == 'GET':
            row = self.cache.get(q['key'].removeprefix('eq.'))
            now = datetime.fromisoformat(q['expires_at'].removeprefix('gt.'))
            return httpx.Response(200, json=[row] if row and datetime.fromisoformat(row['expires_at']) > now else [])
        if path == 'catalog_cache' and req.method == 'POST':
            self.cache[body['key']] = body
            return httpx.Response(201)
        if path == 'catalog_calls' and req.method == 'PATCH':
            self.calls[int(q['id'].removeprefix('eq.')) - 1].update(body)
            return httpx.Response(200, json=[])
        if path == 'works' and req.method == 'GET':
            wid = q['id'].removeprefix('eq.')
            return httpx.Response(200, json=[w for w in self.works.values() if w['id'] == wid])
        name = path.removeprefix('rpc/')
        self.rpc_args.setdefault(name, []).append(body)
        if name == 'begin_catalog_call':
            if self.budget_error:
                code, details = self.budget_error
                return httpx.Response(400, json={'code': code, 'details': details, 'message': 'Used up', 'hint': None})
            self.calls.append({'provider': body['p_provider'], 'user': body['p_user'], 'outcome': 'pending'})
            return httpx.Response(200, json=len(self.calls))
        if name == 'work_from_catalog':
            w = self.works.setdefault(body['p_ref'], {'id': f'work-{len(self.works) + 1}', 'title': body['p_title'],
                                                      'year': body['p_year'], 'kind': body['p_kind'], 'catalog_ref': body['p_ref']})
            return httpx.Response(200, json=w)
        if name == 'create_user_release':
            return httpx.Response(200, json=self.create)
        if name == 'link_release_work':
            return httpx.Response(200, json=self.link)
        raise AssertionError(f'unexpected call {req.method} {req.url}')

    def asked(self, host=None):
        return [r for r in self.requests if host is None or r.url.host == host]


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(catalog_module, 'BACKOFF_SECONDS', 0)


def world(**kw) -> World:
    w = World(**kw)
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(w.handler))
    return w


def search(client, **body):
    r = client.post('/api/catalog/search', headers=AUTH, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# --- titles -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('raw, title, year', [
    ('Princess Mononoke (1997)', 'Princess Mononoke', 1997),     # what the feasibility test's model wrote
    ('Spirited Away', 'Spirited Away', None),
    ('Blade Runner 2049', 'Blade Runner 2049', None),             # a year in the name is part of the name
])
def test_split_year(raw, title, year):
    assert split_year(raw) == (title, year)


@pytest.mark.parametrize('raw, loose', [
    ('Nausicaa Of The Valley Of The Wind (Limited Edition Steelbook) (Blu-ray + DVD)', 'Nausicaa Of The Valley Of The Wind'),
    ('Spirited Away Steelbook Blu-ray', 'Spirited Away'),
    ('Star Trek: Stardate Collection (Blu-ray + Digital Copy) [Blu-ray]', 'Star Trek: Stardate Collection'),
    ("The Legend of Zelda: Tears of the Kingdom Collector's Edition - Nintendo Switch", 'The Legend of Zelda: Tears of the Kingdom'),
])
def test_loosen_strips_edition_and_format_words(raw, loose):
    assert loosen(raw) == loose


def test_norm_title():
    assert norm_title('Nausicaä of the Valley') == norm_title('nausicaa of the valley')
    assert norm_title('The Hobbit') == norm_title('hobbit') and norm_title('Tom & Jerry') == 'tom and jerry'


# --- ranking and strength: never link silently on a weak match ----------------------------------------------------

def test_exact_title_and_year_is_strong(client):
    w = world(tmdb=[tmdb(MONONOKE)])
    r = search(client, title='Princess Mononoke (1997)', kind='movie')
    assert r['status'] == 'ok' and r['step'] == 'exact' and r['strength'] == 'strong'
    assert r['candidates'][0] == {'ref': 'tmdb_movie:128', 'title': 'Princess Mononoke', 'year': 1997, 'kind': 'movie',
                                  'source': 'tmdb', 'detail': 'もののけ姫', 'score': 1.0, 'exact': True}
    sent = w.asked()[0]
    assert sent.url.path == '/3/search/movie'
    assert sent.url.params['query'] == 'Princess Mononoke' and sent.url.params['year'] == '1997'
    assert sent.url.params['api_key'] == TMDB_KEY and 'authorization' not in sent.headers
    assert sent.headers['user-agent'] == 'provenance-catalog/0.1'


def test_two_shows_with_one_title_are_weak_without_a_year(client):
    world(tmdb=[tmdb(AVATAR_2024, AVATAR_2005)])
    r = search(client, title='Avatar: The Last Airbender', kind='tv')
    assert r['strength'] == 'weak' and len(r['candidates']) == 2


def test_the_year_picks_between_them(client):
    world(tmdb=[tmdb(AVATAR_2005)])
    r = search(client, title='Avatar: The Last Airbender', kind='tv', year=2005)
    assert r['strength'] == 'strong' and r['candidates'][0]['ref'] == 'tmdb_tv:246'


def test_a_different_title_is_weak(client):
    world(tmdb=[tmdb({**MONONOKE, 'id': 9, 'title': 'Princess Mononoke: The Making Of', 'original_title': ''})])
    r = search(client, title='Princess Mononoke', kind='movie')
    assert r['strength'] == 'weak'


def test_film_or_show_asks_both(client):
    w = world(tmdb=[tmdb(), tmdb(AVATAR_2005)])
    r = search(client, title='Avatar: The Last Airbender', kind='screen')
    assert [q.url.path for q in w.asked()] == ['/3/search/movie', '/3/search/tv']
    assert r['candidates'][0]['kind'] == 'tv'


# --- fallback order -----------------------------------------------------------------------------------------------

def test_isbn_first_and_nothing_else_when_it_answers(client):
    w = world(ol=[ol(HOBBIT)])
    r = search(client, title='The Hobbit', kind='book', isbn='9780547928227')
    assert r['step'] == 'isbn' and r['strength'] == 'strong' and r['candidates'][0]['ref'] == 'ol_work:OL27482W'
    assert [dict(q.url.params) for q in w.asked()] == [{'q': 'isbn:9780547928227', 'fields': 'key,title,author_name,first_publish_year,edition_count', 'limit': '3'}]
    assert r['sources'] == ['open_library']


def test_isbn_miss_then_exact_title_then_loose_then_nothing(client):
    w = world(ol=[ol(), ol(), ol()])
    r = search(client, title='The Hobbit (Deluxe Edition) Hardcover', kind='book', isbn='9780547928227')
    asked = [q.url.params.get('q') or q.url.params.get('title') for q in w.asked()]
    assert asked == ['isbn:9780547928227', 'The Hobbit (Deluxe Edition) Hardcover', 'The Hobbit']
    assert r['status'] == 'ok' and r['step'] == 'none' and r['candidates'] == []


def test_loose_title_answers_when_the_exact_one_does_not(client):
    w = world(tmdb=[tmdb(), tmdb(MONONOKE)])
    r = search(client, title='Princess Mononoke [Blu-ray] Steelbook (1997)', kind='movie')
    first, second = w.asked()
    assert first.url.params['query'] == 'Princess Mononoke [Blu-ray] Steelbook' and first.url.params['year'] == '1997'
    assert second.url.params['query'] == 'Princess Mononoke' and 'year' not in second.url.params
    assert r['step'] == 'loose' and r['strength'] == 'strong'


def test_a_wrong_year_falls_back_to_no_year(client):
    w = world(tmdb=[tmdb(), tmdb(MONONOKE)])
    r = search(client, title='Princess Mononoke', kind='movie', year=2018)   # the disc's year, not the film's
    assert 'year' not in w.asked()[1].url.params
    assert r['step'] == 'loose' and r['strength'] == 'weak'                  # the year disagrees: not preselected


@pytest.mark.parametrize('kind', ['game', 'other', None])
def test_other_kinds_skip_the_catalog(client, kind):
    w = world()
    r = search(client, title='The Legend of Zelda: Tears of the Kingdom', kind=kind)
    assert r == {'status': 'skipped', 'step': 'none', 'strength': None, 'candidates': [], 'sources': [], 'message': None}
    assert w.requests == [] and w.calls == []


# --- cache --------------------------------------------------------------------------------------------------------

def test_answers_are_cached_and_reused(client):
    w = world(tmdb=[tmdb(MONONOKE)])
    first = search(client, title='Princess Mononoke', kind='movie', year=1997)
    again = search(client, title='Princess Mononoke', kind='movie', year=1997)
    assert first == again and len(w.asked()) == 1 and len(w.calls) == 1
    row = w.cache['tmdb:movie:search:princess mononoke:1997']
    ttl = datetime.fromisoformat(row['expires_at']) - datetime.fromisoformat(row['fetched_at'])
    assert ttl == timedelta(days=30)
    assert w.cache['work:tmdb_movie:128']['response']['title'] == 'Princess Mononoke'   # each candidate, by its ref
    assert TMDB_KEY not in json.dumps(w.cache)


def test_empty_answers_are_cached_for_a_week(client):
    w = world(tmdb=[tmdb(), tmdb()])
    search(client, title='Nothing Like This', kind='movie')
    row = w.cache['tmdb:movie:search:nothing like this:']
    assert datetime.fromisoformat(row['expires_at']) - datetime.fromisoformat(row['fetched_at']) == timedelta(days=7)


# --- catalog down or rate limited: intake still works -------------------------------------------------------------

def test_429_is_unavailable_not_cached_and_pauses(client):
    w = world(tmdb=[tmdb(status=429, headers={'Retry-After': '30'})])
    r = search(client, title='Princess Mononoke', kind='movie')
    assert r['status'] == 'unavailable' and r['message'] and r['candidates'] == []
    assert not w.cache and len(w.asked()) == 1          # one 429 stops the search: the loose step doesn't hammer it
    call = w.calls[0]
    assert call['outcome'] == 'rate_limited' and call['http_status'] == 429 and call['provider'] == 'tmdb'
    wait = datetime.fromisoformat(call['retry_after']) - datetime.now(timezone.utc)
    assert timedelta(seconds=25) < wait <= timedelta(seconds=30)


def test_one_timeout_is_retried(client):
    w = world(tmdb=[httpx.ReadTimeout('slow'), tmdb(MONONOKE)])
    r = search(client, title='Princess Mononoke', kind='movie', year=1997)
    assert r['strength'] == 'strong' and len(w.asked()) == 2 and w.calls[0]['outcome'] == 'hit'


@pytest.mark.parametrize('replies', [
    [(500, {}, {}), (503, {}, {})],
    [httpx.ConnectError('down'), httpx.ConnectError('down')],
    [(200, ['not the shape'], {})],
])
def test_errors_are_unavailable_and_never_cached(client, replies, caplog):
    w = world(tmdb=replies)
    caplog.set_level(logging.DEBUG)
    r = search(client, title='Princess Mononoke', kind='movie')
    assert r['status'] == 'unavailable' and not w.cache and w.calls[0]['outcome'] == 'error'
    assert TMDB_KEY not in caplog.text and 'api_key' not in caplog.text


@pytest.mark.parametrize('code, details', [('PT429', 'user'), ('PT503', 'cooldown')])
def test_spent_budget_is_unavailable_without_asking(client, code, details):
    w = world(budget_error=(code, details))
    r = search(client, title='Princess Mononoke', kind='movie')
    assert r['status'] == 'unavailable' and w.requests == []


def test_open_library_down_is_unavailable(client):
    world(ol=[(502, {}, {}), (502, {}, {})])
    assert search(client, title='The Hobbit', kind='book')['status'] == 'unavailable'


def test_search_takes_only_its_fields(client):
    world()
    assert client.post('/api/catalog/search', headers=AUTH, json={'title': 'x', 'kind': 'movie', 'user_id': 'b'}).status_code == 422
    assert client.post('/api/catalog/search', headers=AUTH, json={'title': 'x', 'kind': 'book', 'isbn': '123'}).status_code == 422
    assert client.post('/api/catalog/search', json={'title': 'x'}).status_code == 401


# --- user-created releases ----------------------------------------------------------------------------------------

def embedding_reply(n=1):
    return 200, {'data': [{'index': i, 'embedding': [0.01] * 512} for i in range(n)], 'usage': {'total_tokens': 17}}, {}


def create(client, **body):
    return client.post('/api/releases', headers=AUTH, json=body)


def test_the_work_comes_from_the_catalog_not_the_client(client):
    w = world(tmdb=[tmdb(MONONOKE)], openai=[embedding_reply()])
    search(client, title='Princess Mononoke', kind='movie', year=1997)          # caches the candidate by its ref
    r = create(client, title='Princess Mononoke', format='bluray', edition='Steelbook', work={'ref': 'tmdb_movie:128'})
    assert r.status_code == 200, r.text
    made = w.rpc_args['work_from_catalog'][0]
    assert made['p_title'] == 'Princess Mononoke' and made['p_year'] == 1997 and made['p_kind'] == 'movie'
    assert made['p_external_ids'] == {'tmdb_movie': 128} and made['p_created_by'] == USER_A
    assert create(client, title='x', work={'ref': 'tmdb_movie:128', 'title': 'Spam'}).status_code == 422


def test_a_ref_not_seen_before_is_fetched_from_the_catalog(client):
    w = world(tmdb=[(200, MONONOKE, {})], openai=[embedding_reply()])
    assert create(client, title='Princess Mononoke', work={'ref': 'tmdb_movie:128'}).status_code == 200
    assert w.asked()[0].url.path == '/3/movie/128'
    assert w.rpc_args['work_from_catalog'][0]['p_title'] == 'Princess Mononoke'


def test_only_catalog_facts_are_shared(client):
    w = world(openai=[embedding_reply()])
    for private in ({'notes': 'birthday gift'}, {'price_paid': 20}, {'occasion_id': USER_A}, {'giver_id': USER_A},
                    {'photo_ids': [USER_A]}, {'location': 'shelf'}, {'condition_grade': 'good'}, {'created_by': USER_A}):
        assert create(client, title='Spirited Away', **private).status_code == 422
    assert w.rpc_args == {}
    r = create(client, title='Spirited Away', format='Blu-ray', edition='Steelbook',
               work={'new': {'title': 'Spirited Away', 'year': 2001, 'kind': 'movie'}})
    assert r.status_code == 200, r.text
    sent = w.rpc_args['create_user_release'][0]
    assert set(sent) == {'p_title', 'p_format', 'p_edition', 'p_barcode', 'p_embedding', 'p_work_id', 'p_new_work',
                         'p_created_by', 'p_max_distance', 'p_declined'}
    assert sent['p_new_work'] == {'title': 'Spirited Away', 'year': 2001, 'kind': 'movie'}
    assert sent['p_created_by'] == USER_A and sent['p_max_distance'] == get_settings().duplicate_max_distance
    embedded = json.loads(w.asked('api.openai.com')[0].content)
    assert embedded == {'model': 'text-embedding-3-small', 'dimensions': 512, 'encoding_format': 'float',
                        'input': ['title: Spirited Away | format: Blu-ray | edition: Steelbook | year: 2001']}
    assert 'sk-test-not-a-real-key' in w.asked('api.openai.com')[0].headers['authorization']


def test_similar_release_is_offered_and_nothing_is_made(client):
    similar = [{'id': 'rel-old', 'barcode': None, 'title': 'Spirited Away', 'edition': 'Steelbook', 'format': 'Blu-ray',
                'release_year': None, 'work_title': 'Spirited Away', 'work_year': 2001, 'distance': 0.0123456}]
    w = world(openai=[embedding_reply()], create={'status': 'similar', 'release': None, 'similar': similar})
    r = create(client, title='spirited away', format='Blu-ray', edition='steel book').json()
    assert r['status'] == 'similar' and r['release'] is None
    assert r['similar'][0]['id'] == 'rel-old' and r['similar'][0]['distance'] == 0.0123
    # "No, mine is different": the same request with it declined; the vector comes from the cache this time
    w.create = {'status': 'created', 'release': {'id': 'rel-new', 'title': 'spirited away'}, 'similar': []}
    r = create(client, title='spirited away', format='Blu-ray', edition='steel book', declined=[USER_A]).json()
    assert r['status'] == 'created' and w.rpc_args['create_user_release'][1]['p_declined'] == [USER_A]
    assert len(w.asked('api.openai.com')) == 1


def test_duplicate_check_down_means_no_shared_release(client):
    w = world(openai=[(500, {'error': {'message': 'Incorrect API key sk-test-xxxx'}}, {})])
    r = create(client, title='Spirited Away', format='Blu-ray').json()
    assert r['status'] == 'unavailable' and r['release'] is None and 'still be saved' in r['message']
    assert 'create_user_release' not in w.rpc_args


def test_with_a_barcode_the_index_guards_even_without_the_check(client):
    w = world(openai=[httpx.ConnectError('down')], create={'status': 'existing', 'release': {'id': 'rel-1'}, 'similar': []})
    r = create(client, title='Code Geass', barcode='704400025105').json()
    assert r['status'] == 'existing'
    sent = w.rpc_args['create_user_release'][0]
    assert sent['p_barcode'] == '0704400025105' and sent['p_embedding'] is None
    assert create(client, title='x', barcode='045496600397').status_code == 422     # check digit


def test_embedding_cap_is_unavailable(client):
    w = world(budget_error=('PT429', 'user'))
    r = create(client, title='Spirited Away').json()
    assert r['status'] == 'unavailable' and w.requests == []


def test_fake_embeddings_only_against_local_supabase(client, monkeypatch):
    world()
    monkeypatch.setattr(get_settings(), 'embeddings_fake', True)
    with pytest.raises(RuntimeError):
        create(client, title='Spirited Away')


# --- linking a work to a barcode release --------------------------------------------------------------------------

def test_link_work_to_a_release_without_one(client):
    w = world(tmdb=[(200, MONONOKE, {})])
    w.link = {'work_id': 'work-1', 'linked': True}
    r = client.post('/api/releases/44444444-4444-4444-8444-444444444444/work', headers=AUTH, json={'ref': 'tmdb_movie:128'}).json()
    assert r == {'linked': True, 'work': {'id': 'work-1', 'title': 'Princess Mononoke', 'year': 1997, 'kind': 'movie',
                                          'catalog_ref': 'tmdb_movie:128'}}


def test_a_release_keeps_the_work_it_has(client):
    w = world(tmdb=[(200, MONONOKE, {})])
    w.works['tmdb_movie:81'] = {'id': 'work-9', 'title': 'Nausicaä', 'year': 1984, 'kind': 'movie', 'catalog_ref': 'tmdb_movie:81'}
    w.link = {'work_id': 'work-9', 'linked': False}
    r = client.post('/api/releases/44444444-4444-4444-8444-444444444444/work', headers=AUTH, json={'ref': 'tmdb_movie:128'}).json()
    assert r['linked'] is False and r['work']['id'] == 'work-9'


def test_link_with_the_catalog_down_is_503(client):
    world(tmdb=[(500, {}, {}), (500, {}, {})])
    r = client.post('/api/releases/44444444-4444-4444-8444-444444444444/work', headers=AUTH, json={'ref': 'tmdb_movie:128'})
    assert r.status_code == 503 and 'without linking' in r.json()['detail']['message']


# --- canonical text and the fake vectors --------------------------------------------------------------------------

def test_canonical_text():
    assert canonical_text('Dune', 'paperback', None, 1990) == canonical_text('Dune', 'Paperback', 'standard', 1990)
    assert canonical_text('Zelda', 'Nintendo Switch', '', None) == 'title: Zelda | format: Switch | edition: Standard | year: unknown'
    assert norm_format('4K Ultra HD + Blu-ray') == '4K UHD' and norm_format('hardback') == 'Hardcover'


def test_fake_vectors_put_shared_words_close():
    def dist(a, b):
        return 1 - sum(x * y for x, y in zip(fake_vector(a), fake_vector(b)))
    same = dist(canonical_text('Spirited Away', 'Blu-ray'), canonical_text('spirited away', 'Blu-ray'))
    other = dist(canonical_text('Spirited Away', 'Blu-ray'), canonical_text('Princess Mononoke', 'DVD'))
    assert same < 1e-9 and other > 0.3
