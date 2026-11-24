"""Photo upload, read and delete with no network: Supabase is the same mock transport as test_api.py.

Whether Postgres RLS and the bucket policies really keep user B out is proven in tests/db/test_photos_storage.py
(real policies) and tests/test_live_photos.py (real Storage service). Here: what the backend sends, and how it
reacts when Supabase says no.
"""
import io
import json
import logging

import pytest
from PIL import Image

import photo_images as P
from app.images import MAX_EDGE
from app.photos import MAX_UPLOAD_BYTES
from test_api import AUTH, ITEM, USER_A, FakeSupabase, client, use  # noqa: F401 (client is a fixture)

PHOTO = '44444444-4444-4444-8444-444444444444'
PATH = f'{USER_A}/{PHOTO}.jpg'
ROW = {'id': PHOTO, 'item_id': ITEM, 'taken_at': None, 'width': 200, 'height': 300, 'position': 0,
       'created_at': '2026-11-24T00:00:00+00:00', 'storage_path': PATH}
OK_UPLOAD = (200, {'Key': f'photos/{PATH}'})


def upload(client, data, url=f'/api/items/{ITEM}/photos', name='photo.jpg', headers=AUTH):
    return client.post(url, headers=headers, files={'file': (name, data, 'image/jpeg')})


def calls_to(fake, part):
    return [c for c in fake.calls if part in c.url.path]


def jpeg_of(call) -> Image.Image:
    return Image.open(io.BytesIO(call.content))


# --- what is stored: metadata, date, orientation, size ------------------------------------------------------

def test_gps_and_exif_are_gone_from_the_file_but_the_date_is_kept_in_the_row(client):
    original = P.make('JPEG')
    assert all(s in original for s in P.SECRETS[:4])  # the fixture really does carry the secrets
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, []), OK_UPLOAD, (201, [ROW])]))
    assert upload(client, original).status_code == 201

    stored = calls_to(fake, '/storage/v1/object/photos/')[0].content
    assert not any(s in stored for s in P.SECRETS)
    assert set(P.jpeg_segments(stored)) <= {0xE0, 0xDB, 0xC0, 0xC4}  # JFIF header + image tables only: no APP1 (EXIF/XMP), no comment
    assert dict(Image.open(io.BytesIO(stored)).getexif()) == {}
    # The date went to the database row instead, with the camera's own UTC offset.
    assert json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)['taken_at'] == '2021-11-25T10:30:00-07:00'


def test_orientation_is_applied(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, []), OK_UPLOAD, (201, [ROW])]))
    upload(client, P.make('JPEG', size=(300, 200), orientation=6))  # stored sideways, tagged "rotate 90 clockwise"
    img = jpeg_of(calls_to(fake, '/storage/v1/object/photos/')[0])
    assert img.size == (200, 300)  # now portrait
    red, blue = img.getpixel((190, 10)), img.getpixel((10, 10))  # the red corner moved from top-left to top-right
    assert red[0] > 200 and red[2] < 60 and blue[2] > 200 and blue[0] < 60
    row = json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)
    assert (row['width'], row['height']) == (200, 300)  # the row records the upright size


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'HEIF'])
def test_jpeg_png_and_heic_are_accepted_and_come_out_as_clean_jpeg(client, fmt):
    fake = use(client, FakeSupabase([OK_UPLOAD, (201, [ROW])]))
    assert upload(client, P.make(fmt), url='/api/photos').status_code == 201
    stored = calls_to(fake, '/storage/v1/object/photos/')[0].content
    assert stored[:2] == b'\xff\xd8' and not any(s in stored for s in P.SECRETS)
    assert json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)['taken_at'] == '2021-11-25T10:30:00-07:00'


def test_long_edge_is_capped_at_2048_and_small_photos_are_not_enlarged(client):
    fake = use(client, FakeSupabase([OK_UPLOAD, (201, [ROW]), OK_UPLOAD, (201, [ROW])]))
    upload(client, P.make(size=(4000, 1000), orientation=1), url='/api/photos')
    upload(client, P.make(size=(300, 200), orientation=1), url='/api/photos')
    big, small = (jpeg_of(c).size for c in calls_to(fake, '/storage/v1/object/photos/'))
    assert big == (MAX_EDGE, 512) and small == (300, 200)


def test_no_date_taken_is_saved_as_null_and_a_bad_date_never_blocks_the_upload(client):
    fake = use(client, FakeSupabase([OK_UPLOAD, (201, [ROW]), OK_UPLOAD, (201, [ROW])]))
    assert upload(client, P.make(date=None), url='/api/photos').status_code == 201
    assert upload(client, P.make(date='0000:00:00 00:00:00'), url='/api/photos').status_code == 201
    inserts = [json.loads(c.content) for c in calls_to(fake, '/rest/v1/photos')]
    assert [i['taken_at'] for i in inserts] == [None, None]


def test_transparent_png_goes_on_white_and_a_colour_profile_is_converted_not_left_behind():
    from PIL import ImageCms
    from app.images import clean_photo
    out = io.BytesIO()
    Image.new('RGBA', (50, 50), (255, 0, 0, 0)).save(out, 'PNG')  # fully transparent
    assert Image.open(io.BytesIO(clean_photo(out.getvalue()).jpeg)).getpixel((5, 5))[0] > 250  # white, not black
    prof = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    out = io.BytesIO()
    P.picture().save(out, 'JPEG', icc_profile=prof)
    stored = clean_photo(out.getvalue()).jpeg
    assert b'ICC_PROFILE' not in stored and b'ICC_PROFILE' in out.getvalue()
    clean_photo(_with_icc(b'not a real profile'))  # a broken profile is ignored, not fatal


def _with_icc(profile: bytes) -> bytes:
    out = io.BytesIO()
    P.picture().save(out, 'JPEG', icc_profile=profile)
    return out.getvalue()


# --- rejected uploads never reach storage or the database ---------------------------------------------------

def _gif():
    out = io.BytesIO()
    P.picture().save(out, 'GIF')
    return out.getvalue()


def _webp():
    out = io.BytesIO()
    P.picture().save(out, 'WEBP')
    return out.getvalue()


@pytest.mark.parametrize('data', [_gif(), _webp(), b'%PDF-1.7 not a photo', b'just text, renamed .jpg', b'', b'<svg xmlns="http://www.w3.org/2000/svg"/>'])
def test_wrong_file_type_is_415_and_touches_nothing(client, data):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}])]))
    r = upload(client, data)
    assert r.status_code == 415 and 'JPEG, PNG and HEIC' in r.json()['detail']['message']
    assert not calls_to(fake, '/storage/') and not calls_to(fake, '/rest/v1/photos')


def test_oversized_file_is_413_and_touches_nothing(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}])]))
    r = upload(client, b'\xff\xd8' + b'0' * MAX_UPLOAD_BYTES)
    assert r.status_code == 413 and 'limit' in r.json()['detail']['message']
    assert not calls_to(fake, '/storage/') and not calls_to(fake, '/rest/v1/photos')


def test_damaged_jpeg_and_pixel_bomb_are_422(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, [{'id': ITEM}])]))
    good = P.make('JPEG', orientation=1)
    assert upload(client, good[: len(good) // 2]).status_code == 422
    bomb = io.BytesIO()
    Image.new('L', (9000, 9000)).save(bomb, 'PNG')  # 81 megapixels, a few KB of file
    r = upload(client, bomb.getvalue())
    assert r.status_code == 422 and 'too many pixels' in r.json()['detail']['message']
    assert not calls_to(fake, '/storage/')


def test_unauthenticated_requests_are_401(client):
    fake = use(client, FakeSupabase(auth=(401, {'msg': 'invalid JWT'})))
    for headers in ({}, {'Authorization': 'Bearer forged'}):
        assert upload(client, P.make(), headers=headers).status_code == 401
        assert upload(client, P.make(), url='/api/photos', headers=headers).status_code == 401
        assert client.get(f'/api/items/{ITEM}/photos', headers=headers).status_code == 401
        assert client.delete(f'/api/photos/{PHOTO}', headers=headers).status_code == 401
    assert not fake.calls


# --- who the backend acts as, and what it hands back --------------------------------------------------------

def test_storage_is_called_as_the_user_never_with_the_service_key_and_the_path_is_owner_prefixed(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, []), OK_UPLOAD, (201, [ROW])]))
    upload(client, P.make())
    for call in fake.calls:
        assert call.headers['authorization'] == 'Bearer good' and call.headers['apikey'] == 'anon-test'
    put = calls_to(fake, '/storage/v1/object/photos/')[0]
    owner, _, name = put.url.path.removeprefix('/storage/v1/object/photos/').partition('/')
    assert owner == USER_A and name.endswith('.jpg') and put.headers['content-type'] == 'image/jpeg'
    row = json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)
    assert row['storage_path'] == f'{owner}/{name}' and row['id'] == name.removesuffix('.jpg')
    assert 'owner_id' not in row  # the column defaults to auth.uid()


def test_response_has_no_url_and_no_storage_path_and_nothing_is_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    use(client, FakeSupabase([OK_UPLOAD, (201, [ROW])]))
    r = upload(client, P.make(), url='/api/photos')
    assert r.status_code == 201 and r.json()['id'] == PHOTO
    assert 'storage_path' not in r.json() and 'url' not in r.json() and 'http' not in r.text
    assert '/object/public/' not in caplog.text and 'token=' not in caplog.text  # no public or signed URL in the logs


def test_unattached_photo_has_no_item_and_skips_the_position_lookup(client):
    fake = use(client, FakeSupabase([OK_UPLOAD, (201, [{**ROW, 'item_id': None}])]))
    assert upload(client, P.make(), url='/api/photos').status_code == 201
    assert 'item_id' not in json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)
    assert len(fake.calls) == 2  # upload + insert, no selects


@pytest.mark.parametrize('existing, expected', [([], 0), ([{'position': 0}], 1), ([{'position': 4}], 5)])
def test_new_photo_goes_after_the_last_one_on_the_item(client, existing, expected):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, existing), OK_UPLOAD, (201, [ROW])]))
    upload(client, P.make())
    assert json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)['position'] == expected
    lookup = calls_to(fake, '/rest/v1/photos')[0].url.params
    assert lookup['order'] == 'position.desc' and lookup['limit'] == '1'


# --- user B: the database hides A's rows, so the backend answers 404 and does nothing --------------------------

def test_other_users_item_is_404_and_nothing_is_uploaded(client):
    fake = use(client, FakeSupabase([(200, [])]))  # RLS: B's query for A's item returns no rows
    assert upload(client, P.make()).status_code == 404
    assert not calls_to(fake, '/storage/') and not calls_to(fake, '/rest/v1/photos')


def test_other_users_photo_and_item_listing_and_delete_are_404(client):
    fake = use(client, FakeSupabase([(200, []), (200, []), (200, [])]))
    assert client.get(f'/api/items/{ITEM}/photos', headers=AUTH).status_code == 404  # no rows, and the item is hidden too
    assert client.delete(f'/api/photos/{PHOTO}', headers=AUTH).status_code == 404
    assert client.delete(f'/api/items/{ITEM}', headers=AUTH).status_code == 404
    assert not calls_to(fake, '/storage/')  # no file was touched


def test_foreign_key_failure_for_a_foreign_item_removes_the_uploaded_file(client):
    """Even if the item check were bypassed, the composite (owner_id, item_id) key refuses: the file is cleaned up."""
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, []), OK_UPLOAD,
                                     (409, {'message': 'violates foreign key constraint', 'code': '23503'}), (200, [])]))
    r = upload(client, P.make())
    assert r.status_code == 409
    gone = calls_to(fake, '/storage/v1/object/photos')[-1]
    assert gone.method == 'DELETE' and json.loads(gone.content)['prefixes'] == [json.loads(calls_to(fake, '/rest/v1/photos')[-1].content)['storage_path']]


# --- no silent orphans --------------------------------------------------------------------------------------

def test_row_failure_after_upload_deletes_the_file(client):
    fake = use(client, FakeSupabase([OK_UPLOAD, (500, {'message': 'db down'}), (200, [])]))
    assert upload(client, P.make(), url='/api/photos').status_code == 502
    put, gone = calls_to(fake, '/storage/')
    assert put.method == 'POST' and gone.method == 'DELETE'
    assert json.loads(gone.content)['prefixes'][0] == put.url.path.removeprefix('/storage/v1/object/photos/')


def test_if_the_cleanup_also_fails_it_is_logged_with_the_path(client, caplog):
    use(client, FakeSupabase([OK_UPLOAD, (500, {'message': 'db down'}), (500, {'message': 'storage down'})]))
    assert upload(client, P.make(), url='/api/photos').status_code == 502
    assert 'Orphaned photo file' in caplog.text and USER_A in caplog.text


def test_failed_upload_to_storage_writes_no_row(client):
    fake = use(client, FakeSupabase([(200, [{'id': ITEM}]), (200, []), (500, {'message': 'storage down'})]))
    assert upload(client, P.make()).status_code == 502
    assert len(calls_to(fake, '/rest/v1/photos')) == 1  # only the position lookup


def test_delete_removes_the_file_first_then_the_row(client):
    fake = use(client, FakeSupabase([(200, [{'id': PHOTO, 'storage_path': PATH}]), (200, []), (200, [{'id': PHOTO}])]))
    assert client.delete(f'/api/photos/{PHOTO}', headers=AUTH).status_code == 204
    select, storage, delete = fake.calls
    assert storage.method == 'DELETE' and storage.url.path == '/storage/v1/object/photos'
    assert json.loads(storage.content) == {'prefixes': [PATH]}
    assert delete.method == 'DELETE' and delete.url.params['id'] == f'eq.{PHOTO}'


def test_file_delete_failure_changes_nothing_so_it_can_be_retried(client):
    fake = use(client, FakeSupabase([(200, [{'id': PHOTO, 'storage_path': PATH}]), (500, {'message': 'storage down'})]))
    r = client.delete(f'/api/photos/{PHOTO}', headers=AUTH)
    assert r.status_code == 502 and 'nothing was deleted' in r.json()['detail']['message']
    assert len(fake.calls) == 2  # the row was never deleted


def test_row_delete_failure_after_the_file_is_gone_says_to_delete_again(client, caplog):
    use(client, FakeSupabase([(200, [{'id': PHOTO, 'storage_path': PATH}]), (200, []), (500, {'message': 'db down'})]))
    r = client.delete(f'/api/photos/{PHOTO}', headers=AUTH)
    assert r.status_code == 502 and 'delete again' in r.json()['detail']['message']
    assert 'Deleted the file' in caplog.text and PHOTO in caplog.text


def test_deleting_an_item_removes_its_photo_files_first(client):
    fake = use(client, FakeSupabase([(200, [{'storage_path': PATH}]), (200, []), (200, [{'id': ITEM}])]))
    assert client.delete(f'/api/items/{ITEM}', headers=AUTH).status_code == 204
    assert [c.method for c in fake.calls] == ['GET', 'DELETE', 'DELETE']
    assert json.loads(fake.calls[1].content) == {'prefixes': [PATH]} and fake.calls[2].url.path == '/rest/v1/items'


def test_item_is_kept_if_its_files_cannot_be_deleted(client):
    fake = use(client, FakeSupabase([(200, [{'storage_path': PATH}]), (500, {'message': 'storage down'})]))
    assert client.delete(f'/api/items/{ITEM}', headers=AUTH).status_code == 502
    assert not calls_to(fake, '/rest/v1/items')


# --- reading: signed URLs ---------------------------------------------------------------------------------

def test_list_returns_signed_urls_for_an_hour_in_order_and_never_the_storage_path(client, caplog):
    caplog.set_level(logging.DEBUG)
    second = {**ROW, 'id': '55555555-5555-4555-8555-555555555555', 'position': 1,
              'storage_path': f'{USER_A}/55555555-5555-4555-8555-555555555555.jpg', 'taken_at': '2021-11-25T10:30:00-07:00'}
    signed = [{'path': r['storage_path'], 'signedURL': f'/object/sign/photos/{r["storage_path"]}?token=SECRET{i}', 'error': None}
              for i, r in enumerate([ROW, second])]
    fake = use(client, FakeSupabase([(200, [ROW, second]), (200, signed)]))
    r = client.get(f'/api/items/{ITEM}/photos', headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert [p['id'] for p in body] == [PHOTO, second['id']] and body[1]['taken_at'] == '2021-11-25T10:30:00-07:00'
    assert body[0]['url'] == f'https://test.supabase.invalid/storage/v1/object/sign/photos/{PATH}?token=SECRET0'
    assert all('storage_path' not in p and p['url_expires_in'] == 3600 for p in body)
    sign = fake.calls[1]
    assert sign.url.path == '/storage/v1/object/sign/photos' and json.loads(sign.content) == {
        'expiresIn': 3600, 'paths': [ROW['storage_path'], second['storage_path']]}
    assert fake.calls[0].url.params['order'] == 'position.asc,created_at.asc'
    assert 'SECRET' not in caplog.text  # a signed URL is a bearer credential: it is never logged


def test_list_marks_a_photo_with_no_readable_file_as_null_and_an_empty_item_as_empty(client):
    use(client, FakeSupabase([(200, [ROW]), (200, [{'path': PATH, 'signedURL': None, 'error': 'not found'}])]))
    assert client.get(f'/api/items/{ITEM}/photos', headers=AUTH).json()[0]['url'] is None
    fake = use(client, FakeSupabase([(200, []), (200, [{'id': ITEM}])]))
    assert client.get(f'/api/items/{ITEM}/photos', headers=AUTH).json() == []
    assert not calls_to(fake, '/storage/')
