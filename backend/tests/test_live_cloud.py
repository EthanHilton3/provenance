"""End to end against the REAL Supabase project in .env. Opt in: PROVENANCE_LIVE=1 pytest tests/test_live_cloud.py

Creates two throwaway users, checks auth, RLS isolation, optimistic locking and keyset paging through the real API,
then deletes the users (which cascades to their items).
"""
import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get('PROVENANCE_LIVE'), reason='set PROVENANCE_LIVE=1 to run')


@pytest.fixture(scope='module')
def env():
    from app.config import get_settings
    s = get_settings()
    assert 'invalid' not in s.supabase_url, 'live test must use the real .env'
    return s


@pytest.fixture(scope='module')
def users(env):
    admin = {'apikey': env.supabase_service_role_key.get_secret_value(),
             'Authorization': f'Bearer {env.supabase_service_role_key.get_secret_value()}'}
    anon = {'apikey': env.supabase_anon_key.get_secret_value()}
    created = []
    out = []
    with httpx.Client(timeout=30) as h:
        for tag in ('a', 'b'):
            email, pw = f'live-{tag}-{uuid.uuid4().hex[:8]}@example.com', uuid.uuid4().hex + 'Aa1!'
            r = h.post(f'{env.supabase_auth_url}/admin/users', headers=admin,
                       json={'email': email, 'password': pw, 'email_confirm': True})
            r.raise_for_status()
            uid = r.json()['id']
            created.append(uid)
            t = h.post(f'{env.supabase_auth_url}/token?grant_type=password', headers=anon, json={'email': email, 'password': pw})
            t.raise_for_status()
            out.append({'id': uid, 'headers': {'Authorization': f'Bearer {t.json()["access_token"]}'}})
        try:
            yield out
        finally:
            for uid in created:
                h.delete(f'{env.supabase_auth_url}/admin/users/{uid}', headers=admin)


@pytest.fixture(scope='module')
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_live_flow(client, users):
    a, b = users
    assert client.get('/api/me').status_code == 401
    assert client.get('/api/me', headers={'Authorization': 'Bearer forged'}).status_code == 401
    assert client.get('/api/me', headers=a['headers']).json()['id'] == a['id']

    cats = client.get('/api/categories', headers=a['headers']).json()
    assert len(cats) >= 30
    cat = cats[0]['id']
    assert isinstance(client.get(f'/api/categories/{cat}/fields', headers=a['headers']).json(), list)

    # create: owner is the caller, even though the API never sent it
    made = client.post('/api/items', headers=a['headers'], json={'name': 'Test item', 'category_id': cat,
                                                                   'price_paid': '12.50', 'attributes': {'brand': 'X'}})
    assert made.status_code == 201, made.text
    item = made.json()
    assert item['owner_id'] == a['id'] and item['version'] == 1

    # user B cannot see, edit or delete A's item
    assert client.get(f'/api/items/{item["id"]}', headers=b['headers']).status_code == 404
    assert client.get('/api/items', headers=b['headers']).json() == []
    assert client.patch(f'/api/items/{item["id"]}', headers=b['headers'], json={'version': 1, 'name': 'hax'}).status_code == 404
    assert client.delete(f'/api/items/{item["id"]}', headers=b['headers']).status_code == 404

    # optimistic locking
    ok = client.patch(f'/api/items/{item["id"]}', headers=a['headers'], json={'version': 1, 'name': 'Renamed'})
    assert ok.status_code == 200 and ok.json()['version'] == 2 and ok.json()['name'] == 'Renamed'
    stale = client.patch(f'/api/items/{item["id"]}', headers=a['headers'], json={'version': 1, 'name': 'Stale'})
    assert stale.status_code == 409 and stale.json()['detail']['current']['name'] == 'Renamed'

    # B cannot attach an item to A's data or fake ownership
    assert client.post('/api/items', headers=b['headers'], json={'name': 'x', 'category_id': cat, 'owner_id': a['id']}).status_code == 422
    assert client.post('/api/items', headers=b['headers'],
                       json={'name': 'x', 'category_id': cat, 'parent_item_id': item['id']}).status_code in (400, 403, 409)

    # keyset paging: 5 items, pages of 2, no repeats or gaps
    for i in range(4):
        assert client.post('/api/items', headers=a['headers'], json={'name': f'n{i}', 'category_id': cat}).status_code == 201
    seen, cursor = [], {}
    for _ in range(5):
        page = client.get('/api/items', headers=a['headers'], params={'limit': 2, **cursor}).json()
        if not page:
            break
        seen += [r['id'] for r in page]
        cursor = {'before_created_at': page[-1]['created_at'], 'before_id': page[-1]['id']}
    assert len(seen) == 5 and len(set(seen)) == 5

    assert client.delete(f'/api/items/{item["id"]}', headers=a['headers']).status_code == 204
    assert client.get(f'/api/items/{item["id"]}', headers=a['headers']).status_code == 404
