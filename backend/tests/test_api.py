"""No network: Supabase is replaced by a mock transport that records what the backend sends it."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

USER_A = '11111111-1111-4111-8111-111111111111'
CAT = '22222222-2222-4222-8222-222222222222'
ITEM = '33333333-3333-4333-8333-333333333333'
AUTH = {'Authorization': 'Bearer good'}


class FakeSupabase:
    """Answers /auth/v1/user as USER_A and records every PostgREST call; `rest` is the canned reply."""

    def __init__(self, rest_replies=None, auth=(200, {'id': USER_A, 'email': 'a@example.com'})):
        self.calls: list[httpx.Request] = []
        self.rest_replies = list(rest_replies or [])
        self.auth = auth

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == '/auth/v1/user':
                return httpx.Response(self.auth[0], json=self.auth[1])
            self.calls.append(request)
            status, body = self.rest_replies.pop(0) if self.rest_replies else (200, [])
            return httpx.Response(status, json=body)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def use(client, fake: FakeSupabase):
    app.state.http = fake.client()
    return fake


def test_health_needs_no_token(client):
    assert client.get('/api/health').json() == {'ok': True}


def test_no_or_bad_token_is_401(client):
    use(client, FakeSupabase(auth=(401, {'msg': 'invalid JWT'})))
    assert client.get('/api/me').status_code == 401
    assert client.get('/api/items', headers={'Authorization': 'Basic abc'}).status_code == 401
    assert client.get('/api/items', headers={'Authorization': 'Bearer forged'}).status_code == 401


def test_identity_comes_from_supabase(client):
    use(client, FakeSupabase())
    assert client.get('/api/me', headers=AUTH).json() == {'id': USER_A, 'email': 'a@example.com'}


def test_user_token_is_forwarded_so_rls_applies(client):
    fake = use(client, FakeSupabase([(200, [])]))
    client.get('/api/items', headers=AUTH)
    assert fake.calls[0].headers['authorization'] == 'Bearer good'
    assert fake.calls[0].headers['apikey'] == 'anon-test'  # never the service key


def test_create_never_sends_owner_and_rejects_extras(client):
    fake = use(client, FakeSupabase([(201, [{'id': ITEM}])]))
    r = client.post('/api/items', headers=AUTH, json={'name': 'Zelda', 'category_id': CAT})
    assert r.status_code == 201
    assert 'owner_id' not in json.loads(fake.calls[0].content)
    for extra in ({'owner_id': USER_A}, {'version': 9}, {'id': ITEM}):
        assert client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT, **extra}).status_code == 422
    assert client.post('/api/items', headers=AUTH, json={'name': '  ', 'category_id': CAT}).status_code == 422
    assert client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': 'nope'}).status_code == 422
    assert client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT, 'price_paid': -1}).status_code == 422


def test_update_sends_version_filter_and_only_sent_fields(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM, 'version': 4}])]))
    r = client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 3, 'location': None})
    assert r.status_code == 200
    call = fake.calls[0]
    assert call.method == 'PATCH'
    assert call.url.params['version'] == 'eq.3' and call.url.params['id'] == f'eq.{ITEM}'
    assert json.loads(call.content) == {'location': None}  # explicit null clears; unsent fields are untouched


def test_stale_version_is_409_with_current_row(client):
    current = {'id': ITEM, 'version': 5, 'name': 'Theirs'}
    use(client, FakeSupabase([(200, []), (200, [current])]))
    r = client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 3, 'name': 'Mine'})
    assert r.status_code == 409 and r.json()['detail']['current'] == current


def test_update_of_missing_or_foreign_item_is_404(client):
    use(client, FakeSupabase([(200, []), (200, [])]))
    assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 1, 'name': 'x'}).status_code == 404


def test_update_validation(client):
    use(client, FakeSupabase())
    assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 1}).status_code == 422
    assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 1, 'name': None}).status_code == 422
    assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'name': 'x'}).status_code == 422
    assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 1, 'owner_id': USER_A}).status_code == 422


def test_delete_and_get_404(client):
    use(client, FakeSupabase([(200, []), (200, [])]))
    assert client.delete(f'/api/items/{ITEM}', headers=AUTH).status_code == 404
    assert client.get(f'/api/items/{ITEM}', headers=AUTH).status_code == 404


def test_list_limit_and_keyset_cursor(client):
    fake = use(client, FakeSupabase([(200, []), (200, [])]))
    assert client.get('/api/items?limit=500', headers=AUTH).status_code == 422
    assert client.get('/api/items?before_id=' + ITEM, headers=AUTH).status_code == 422
    client.get(f'/api/items?limit=10&before_created_at=2026-01-01T00:00:00%2B00:00&before_id={ITEM}', headers=AUTH)
    p = fake.calls[0].url.params
    assert p['limit'] == '10' and 'created_at.lt' in p['or'] and ITEM in p['or']


def test_database_errors_map_to_client_status(client):
    use(client, FakeSupabase([(403, {'message': 'new row violates row-level security policy', 'code': '42501'})]))
    r = client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT})
    assert r.status_code == 403 and r.json()['code'] == '42501'
    use(client, FakeSupabase([(500, {'message': 'boom'})]))
    assert client.get('/api/items', headers=AUTH).status_code == 502


def test_auth_outage_is_503_not_401(client):
    for status in (429, 500, 502):
        use(client, FakeSupabase(auth=(status, {'msg': 'busy'})))
        assert client.get('/api/me', headers=AUTH).status_code == 503
    use(client, FakeSupabase(auth=(403, {'msg': 'forbidden'})))
    assert client.get('/api/me', headers=AUTH).status_code == 401


@pytest.mark.parametrize('reply', [
    httpx.Response(200, text='<html>captive portal</html>'),
    httpx.Response(200, json=[]),
    httpx.Response(200, json=None),
    httpx.Response(200, json={'id': 'not-a-uuid'}),
    httpx.Response(200, json={'email': 'a@example.com'}),
])
def test_malformed_auth_reply_is_503_not_500(client, reply):
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: reply))
    assert client.get('/api/me', headers=AUTH).status_code == 503


def test_bad_cursor_is_422_and_good_cursor_is_normalised(client):
    fake = use(client, FakeSupabase([(200, [])]))
    assert client.get(f'/api/items?before_created_at=foo&before_id={ITEM}', headers=AUTH).status_code == 422
    assert client.get(f'/api/items?before_created_at=2026-01-01%22&before_id={ITEM}', headers=AUTH).status_code == 422
    assert client.get(f'/api/items?before_created_at=2026-01-01T00:00:00Z&before_id={ITEM}', headers=AUTH).status_code == 200
    assert '2026-01-01T00:00:00+00:00' in fake.calls[0].url.params['or']


def test_db_4xx_pass_through_with_one_detail_shape(client):
    use(client, FakeSupabase([(409, {'message': 'duplicate key', 'code': '23505'}), (404, {'message': 'no rpc', 'code': 'PGRST202'})]))
    r = client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT})
    assert r.status_code == 409 and r.json() == {'detail': {'message': 'duplicate key'}, 'code': '23505'}
    assert client.get(f'/api/categories/{CAT}/fields', headers=AUTH).status_code == 404


def test_service_key_is_only_needed_when_used(monkeypatch):
    from app import config, db
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', '')
    config.get_settings.cache_clear()
    try:
        assert config.get_settings().supabase_service_role_key.get_secret_value() == ''
        with pytest.raises(RuntimeError):
            db.service_db(None)
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()


def test_franchise_brand_and_signed_by_round_trip_on_create(client):
    saved = {'id': ITEM, 'franchise': 'Zelda', 'brand': 'Nintendo', 'signed_by': 'Eiji Aonuma'}
    fake = use(client, FakeSupabase([(201, [saved])]))
    r = client.post('/api/items', headers=AUTH, json={
        'name': 'Signed poster', 'category_id': CAT, 'franchise': ' Zelda ', 'brand': 'Nintendo', 'signed_by': 'Eiji Aonuma'})
    assert r.status_code == 201 and r.json() == saved
    sent = json.loads(fake.calls[0].content)
    assert (sent['franchise'], sent['brand'], sent['signed_by']) == ('Zelda', 'Nintendo', 'Eiji Aonuma')  # trimmed
    # Not sent means null, like the other optional columns.
    fake = use(client, FakeSupabase([(201, [{'id': ITEM}])]))
    client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT})
    sent = json.loads(fake.calls[0].content)
    assert sent['franchise'] is None and sent['brand'] is None and sent['signed_by'] is None


def test_new_columns_are_length_checked(client):
    use(client, FakeSupabase())
    for col in ('franchise', 'brand', 'signed_by'):
        assert client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT, col: 'x' * 301}).status_code == 422
        assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 1, col: 'x' * 301}).status_code == 422


def test_patch_sends_only_the_new_columns_that_changed(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM, 'version': 8}])]))
    r = client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 7, 'brand': 'Sony', 'franchise': None})
    assert r.status_code == 200
    assert json.loads(fake.calls[0].content) == {'brand': 'Sony', 'franchise': None}  # null clears; signed_by untouched
    assert fake.calls[0].url.params['version'] == 'eq.7'


def test_stale_edit_of_a_new_column_is_409_with_their_values(client):
    current = {'id': ITEM, 'version': 6, 'brand': 'Theirs', 'franchise': 'Zelda', 'signed_by': None}
    use(client, FakeSupabase([(200, []), (200, [current])]))
    r = client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 5, 'brand': 'Mine'})
    assert r.status_code == 409 and r.json()['detail']['current'] == current


def test_categories_include_descriptions(client):
    fake = use(client, FakeSupabase([(200, [])]))
    client.get('/api/categories', headers=AUTH)
    assert fake.calls[0].url.params['select'].split(',') == ['id', 'parent_id', 'name', 'owner_id', 'description']


def test_attributes_must_be_plain_values_and_the_error_names_the_key(client):
    use(client, FakeSupabase())
    base = {'name': 'x', 'category_id': CAT}
    for bad in ({'material': {'a': 1}}, {'tags': ['a', 'b']}, {'piece_count': None}, {'k' * 65: 'v'}, {'': 'v'}, {'note': 'x' * 1001}):
        assert client.post('/api/items', headers=AUTH, json={**base, 'attributes': bad}).status_code == 422, bad
        assert client.patch(f'/api/items/{ITEM}', headers=AUTH, json={'version': 1, 'attributes': bad}).status_code == 422, bad
    assert client.post('/api/items', headers=AUTH, json={**base, 'attributes': {f'k{i}': 'v' for i in range(101)}}).status_code == 422
    loc = client.post('/api/items', headers=AUTH, json={**base, 'attributes': {'material': {'a': 1}}}).json()['detail'][0]['loc']
    assert loc[:3] == ['body', 'attributes', 'material']


def test_plain_attribute_values_are_stored_as_sent(client):
    attrs = {'material': 'Ceramic', 'piece_count': 3, 'weight': 1.5, 'signed': True}
    fake = use(client, FakeSupabase([(201, [{'id': ITEM}])]))
    assert client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT, 'attributes': attrs}).status_code == 201
    assert json.loads(fake.calls[0].content)['attributes'] == attrs  # True stays true, 3 stays 3
