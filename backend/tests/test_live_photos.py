"""Photos end to end against a REAL Supabase Storage service. Opt in: PROVENANCE_LIVE=1 pytest tests/test_live_photos.py

Runs against whatever SUPABASE_URL points at, with two throwaway users (same fixtures as test_live_cloud.py):
* the cloud project in .env: needs the photos migration pushed there first, or every upload fails;
* or the local stack, which needs no cloud at all: export SUPABASE_URL, SUPABASE_ANON_KEY and
  SUPABASE_SERVICE_ROLE_KEY from `npx supabase status -o env` (API_URL, ANON_KEY, SERVICE_ROLE_KEY) first.
It deletes the photos it uploads.
"""
import io
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image

import photo_images as P
from test_live_cloud import client, env, users  # noqa: F401 (fixtures)

pytestmark = pytest.mark.skipif(not os.environ.get('PROVENANCE_LIVE'), reason='set PROVENANCE_LIVE=1 to run')


def test_live_photo_flow(client, users, env):
    a, b = users
    store = env.supabase_storage_url
    anon = {'apikey': env.supabase_anon_key.get_secret_value()}

    def storage_paths(user):  # the stored paths, read straight from the table as that user
        r = httpx.get(f'{env.supabase_rest_url}/photos?select=storage_path', headers={**anon, **user['headers']})
        return [row['storage_path'] for row in r.json()]

    def has_file(user, path):
        """Does Storage still hold the file, for this user? Asked by requesting a brand-new signed URL, which no CDN
        can answer from cache. (Fetching a URL that was already fetched before a delete can still succeed on the
        hosted project, because its CDN keeps serving cached copies; see the README.)"""
        r = httpx.post(f'{store}/object/sign/photos', headers={**anon, **user['headers']}, json={'expiresIn': 60, 'paths': [path]})
        return any(x.get('signedURL') for x in r.json())

    cat =client.get('/api/categories', headers=a['headers']).json()[0]['id']
    item = client.post('/api/items', headers=a['headers'], json={'name': 'Photo test', 'category_id': cat}).json()['id']
    try:
        # --- upload: stored clean and upright, date kept in the row ---
        up = client.post(f'/api/items/{item}/photos', headers=a['headers'],
                         files={'file': ('IMG_1.jpg', P.make('JPEG'), 'image/jpeg')})
        assert up.status_code == 201, up.text
        photo = up.json()
        assert photo['item_id'] == item and photo['position'] == 0 and (photo['width'], photo['height']) == (200, 300)
        assert 'storage_path' not in photo and 'url' not in photo
        assert datetime.fromisoformat(photo['taken_at']) == datetime(2021, 11, 25, 10, 30, tzinfo=timezone(timedelta(hours=-7)))
        second = client.post(f'/api/items/{item}/photos', headers=a['headers'], files={'file': ('b.png', P.make('PNG'), 'image/png')})
        assert second.status_code == 201 and second.json()['position'] == 1

        # --- read: a signed URL works with no credentials at all, and the file is clean ---
        listed = client.get(f'/api/items/{item}/photos', headers=a['headers']).json()
        assert [p['id'] for p in listed] == [photo['id'], second.json()['id']]
        fetched = httpx.get(listed[0]['url'])
        assert fetched.status_code == 200 and fetched.headers['content-type'] == 'image/jpeg'
        assert not any(s in fetched.content for s in P.SECRETS)
        assert set(P.jpeg_segments(fetched.content)) <= {0xE0, 0xDB, 0xC0, 0xC4}
        assert Image.open(io.BytesIO(fetched.content)).size == (200, 300)

        # --- the bare object path does not: private bucket, so no public URL and no anonymous read ---
        path = storage_paths(a)[0]
        for url, headers in ((f'{store}/object/photos/{path}', {}),
                             (f'{store}/object/photos/{path}', anon),
                             (f'{store}/object/public/photos/{path}', {}),
                             (f'{store}/object/public/photos/{path}', anon),
                             (f'{store}/object/authenticated/photos/{path}', anon)):
            assert 400 <= httpx.get(url, headers=headers).status_code < 500, url
        # ...while the same path with the owner's own token does work (so the refusals above are about access, not a wrong path)
        assert httpx.get(f'{store}/object/authenticated/photos/{path}', headers={**anon, **a['headers']}).status_code == 200

        # --- user B: cannot read, upload to or delete A's item or photo, through the API or straight at Storage ---
        assert client.get(f'/api/items/{item}/photos', headers=b['headers']).status_code == 404
        assert client.post(f'/api/items/{item}/photos', headers=b['headers'],
                           files={'file': ('x.jpg', P.make('JPEG'), 'image/jpeg')}).status_code == 404
        assert client.delete(f'/api/photos/{photo["id"]}', headers=b['headers']).status_code == 404
        assert client.delete(f'/api/items/{item}', headers=b['headers']).status_code == 404
        bh = {**anon, **b['headers']}
        assert httpx.get(f'{store}/object/authenticated/photos/{path}', headers=bh).status_code >= 400
        signed = httpx.post(f'{store}/object/sign/photos', headers=bh, json={'expiresIn': 60, 'paths': [path]})
        assert not any(r.get('signedURL') for r in signed.json())  # B cannot mint a URL for A's file
        owner = path.split('/')[0]
        planted = httpx.post(f'{store}/object/photos/{owner}/{P.DATE_TAKEN.replace(":", "").replace(" ", "")}.jpg',
                             headers={**bh, 'Content-Type': 'image/jpeg'}, content=P.make('JPEG'))
        assert planted.status_code >= 400  # B cannot write under A's prefix
        httpx.request('DELETE', f'{store}/object/photos', headers=bh, json={'prefixes': [path]})
        assert has_file(a, path)  # B's delete removed nothing
        # B also cannot put a non-JPEG in its own prefix: the bucket only accepts image/jpeg
        own = f'{b["id"]}/{os.urandom(4).hex()}.png'
        assert httpx.post(f'{store}/object/photos/{own}', headers={**bh, 'Content-Type': 'image/png'}, content=b'x').status_code >= 400

        # --- bad uploads are refused by the real stack too, with a clear 4xx ---
        assert client.post(f'/api/items/{item}/photos', headers=a['headers'],
                           files={'file': ('x.gif', b'GIF89a', 'image/gif')}).status_code == 415

        # --- unattached photo (intake) ---
        loose = client.post('/api/photos', headers=a['headers'], files={'file': ('c.jpg', P.make('JPEG'), 'image/jpeg')})
        assert loose.status_code == 201 and loose.json()['item_id'] is None and loose.json()['position'] == 0
        assert client.get('/api/items/%s/photos' % item, headers=b['headers']).status_code == 404
        assert client.delete(f'/api/photos/{loose.json()["id"]}', headers=a['headers']).status_code == 204

        # --- delete: row and file are both gone ---
        assert client.delete(f'/api/photos/{photo["id"]}', headers=a['headers']).status_code == 204
        assert not has_file(a, path)
        assert [p['id'] for p in client.get(f'/api/items/{item}/photos', headers=a['headers']).json()] == [second.json()['id']]
        assert client.delete(f'/api/photos/{photo["id"]}', headers=a['headers']).status_code == 404

        # --- deleting the item removes its remaining files too ---
        remaining = storage_paths(a)
        assert len(remaining) == 1
        assert client.delete(f'/api/items/{item}', headers=a['headers']).status_code == 204
        assert not has_file(a, remaining[0])
        assert storage_paths(a) == []
    finally:  # leave nothing behind even if an assertion failed halfway
        paths = storage_paths(a) + storage_paths(b)
        if paths:  # the users' rows go with the users, but their files would not
            service = env.supabase_service_role_key.get_secret_value()
            httpx.request('DELETE', f'{store}/object/photos', json={'prefixes': paths},
                          headers={'apikey': service, 'Authorization': f'Bearer {service}'})
