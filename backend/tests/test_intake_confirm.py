"""Confirm, discard, retry, occasions and the fake model (S10), with no network: Supabase is a fake that answers each
call in order. What the database itself does (one transaction, the job lock, double confirm, cross-user, rollback) is
proven against the real database in tests/db/test_intake_confirm.py and tests/test_live_intake.py.
"""
import asyncio
import base64
import io
import json

import pytest
from PIL import Image

from app.ai import AIError, MODES, Scene
from app.fake_ai import FakeAIClient
from test_api import AUTH, CAT, USER_A, FakeSupabase, client, use  # noqa: F401 (client is a fixture)
from test_intake import CATEGORIES, JOB, PHOTO

OCC = '88888888-8888-4888-8888-888888888888'
PATH = f'{USER_A}/{PHOTO}.jpg'


def job_row(status='needs_review', mode='single', photos=None, items=None):
    return {'id': JOB, 'mode': mode, 'status': status, 'card': {'name': 'x'}, 'error': None, 'attempts': 1,
            'max_attempts': 3, 'occasion_id': None, 'created_at': '2026-11-30T00:00:00+00:00',
            'updated_at': '2026-11-30T00:00:00+00:00',
            'photos': [{'id': PHOTO, 'storage_path': PATH, 'item_id': None, 'width': 2048, 'height': 1536}]
            if photos is None else photos,
            'items': items or []}


def item(name='Zelda', **extra):
    return {'name': name, 'category_id': CAT, **extra}


def calls_to(fake, part):
    return [c for c in fake.calls if part in c.url.path]


SIGNED = (200, [{'path': PATH, 'signedURL': '/object/sign/photos/x?token=t'}])


# --- confirm ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('body', [
    {'items': []},
    {'items': [item()] * 101},
    {'items': [item(owner_id=USER_A)]},          # the owner comes from the token only
    {'items': [item(intake_job_id=JOB)]},        # the job link is set by the database function
    {'items': [item(version=3)]},
    {'items': [item(name='  ')]},
    {'items': [item(attributes={'platform': {'nested': 1}})]},
    {'items': [item(condition_grade='mint')]},
    {'items': [item()], 'job_status': 'done'},
    {},
])
def test_confirm_validates_every_item_before_touching_anything(client, body):
    fake = use(client, FakeSupabase())
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json=body)
    assert r.status_code == 422, r.text
    assert fake.calls == []


def test_confirm_single_sends_the_items_and_no_copies(client):
    done = job_row('done', items=[{'id': 'i1', 'name': 'Zelda'}])
    fake = use(client, FakeSupabase([(200, [job_row()]), (200, [{'id': 'i1'}]), (200, [done]), SIGNED]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH,
                    json={'items': [item(sealed=None, attributes={'platform': 'Switch'}, occasion_id=OCC)]})
    assert r.status_code == 200, r.text
    rpc = calls_to(fake, '/rpc/confirm_intake_job')[0]
    sent = json.loads(rpc.content)
    assert sent['p_job_id'] == JOB and sent['p_copies'] == []
    assert sent['p_items'][0]['sealed'] is None and sent['p_items'][0]['occasion_id'] == OCC
    assert rpc.headers['authorization'] == 'Bearer good'  # as the user, never the service key
    assert calls_to(fake, '/object/copy') == []
    out = r.json()
    assert out['items'] == [{'id': 'i1'}] and out['job']['status'] == 'done' and out['job']['items'][0]['id'] == 'i1'
    assert out['job']['photo']['url'].endswith('token=t') and 'storage_path' not in json.dumps(out)


def test_confirm_group_copies_the_photo_once_per_extra_item(client):
    fake = use(client, FakeSupabase([(200, [job_row(mode='group')]), (200, {}), (200, {}),
                                     (200, [{'id': 'i1'}, {'id': 'i2'}, {'id': 'i3'}]), (200, [job_row('done')]), SIGNED]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item('A'), item('B'), item('C')]})
    assert r.status_code == 200, r.text
    copies = [json.loads(c.content) for c in calls_to(fake, '/object/copy')]
    assert len(copies) == 2 and all(c['sourceKey'] == PATH and c['bucketId'] == 'photos' for c in copies)
    dests = {c['destinationKey'] for c in copies}
    assert len(dests) == 2 and all(d.startswith(f'{USER_A}/') and d != PATH for d in dests)
    sent = json.loads(calls_to(fake, '/rpc/confirm_intake_job')[0].content)
    assert {c['storage_path'] for c in sent['p_copies']} == dests
    assert [i['name'] for i in sent['p_items']] == ['A', 'B', 'C']


def test_confirm_without_a_photo_makes_no_copies(client):
    fake = use(client, FakeSupabase([(200, [job_row('failed', mode='group', photos=[])]), (200, [{'id': 'i1'}, {'id': 'i2'}]),
                                     (200, [job_row('done', photos=[])])]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item('A'), item('B')]})
    assert r.status_code == 200, r.text
    assert calls_to(fake, '/object/copy') == []
    assert json.loads(calls_to(fake, '/rpc/confirm_intake_job')[0].content)['p_copies'] == []


@pytest.mark.parametrize('status', ['done', 'queued', 'processing', 'discarded'])
def test_confirm_of_a_job_not_ready_is_409_and_calls_nothing_else(client, status):
    fake = use(client, FakeSupabase([(200, [job_row(status, items=[{'id': 'i1', 'name': 'Zelda'}])])]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item()]})
    assert r.status_code == 409
    assert r.json()['detail']['job']['status'] == status
    assert len(fake.calls) == 1


def test_losing_the_race_to_another_tab_removes_the_copies_and_is_409(client):
    fake = use(client, FakeSupabase([
        (200, [job_row(mode='group')]), (200, {}),
        (409, {'code': 'PT409', 'message': 'These items are already saved'}),
        (200, []),                                                  # storage delete of the copy
        (200, [job_row('done', items=[{'id': 'i9', 'name': 'From the other tab'}])]),
    ]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item('A'), item('B')]})
    assert r.status_code == 409
    assert r.json()['detail']['job']['items'] == [{'id': 'i9', 'name': 'From the other tab'}]
    copied = json.loads(calls_to(fake, '/object/copy')[0].content)['destinationKey']
    removed = [c for c in fake.calls if c.method == 'DELETE' and '/storage/' in c.url.path]
    assert json.loads(removed[0].content) == {'prefixes': [copied]}


@pytest.mark.parametrize('status,code,expect', [(422, 'PT422', 422), (409, '23503', 422), (400, '23514', 400)])
def test_a_failed_confirm_removes_the_copies(client, status, code, expect):
    fake = use(client, FakeSupabase([(200, [job_row(mode='group')]), (200, {}), (status, {'code': code, 'message': 'no'}),
                                     (200, [])]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item('A'), item('B')]})
    assert r.status_code == expect
    assert [c for c in fake.calls if c.method == 'DELETE' and '/storage/' in c.url.path]


def test_a_failed_copy_saves_nothing(client):
    fake = use(client, FakeSupabase([(200, [job_row(mode='group')]), (200, {}), (500, {'message': 'boom'}), (200, [])]))
    r = client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item('A'), item('B'), item('C')]})
    assert r.status_code == 502
    assert calls_to(fake, '/rpc/confirm_intake_job') == []
    assert [c for c in fake.calls if c.method == 'DELETE' and '/storage/' in c.url.path]  # the copy that worked


def test_confirm_of_someone_elses_job_is_404(client):
    fake = use(client, FakeSupabase([(200, [])]))
    assert client.post(f'/api/intake/jobs/{JOB}/confirm', headers=AUTH, json={'items': [item()]}).status_code == 404
    assert len(fake.calls) == 1


# --- discard and retry ------------------------------------------------------------------------------------

def test_discard_deletes_the_file_then_the_row(client):
    fake = use(client, FakeSupabase([(200, [{'photo_id': PHOTO, 'storage_path': PATH}]), (200, []), (200, [])]))
    assert client.post(f'/api/intake/jobs/{JOB}/discard', headers=AUTH).status_code == 204
    rpc, files, rows = fake.calls
    assert rpc.url.path.endswith('/rpc/discard_intake_job') and json.loads(rpc.content) == {'p_job_id': JOB}
    assert files.method == 'DELETE' and json.loads(files.content) == {'prefixes': [PATH]}
    assert rows.method == 'DELETE' and rows.url.params['id'] == f'in.({PHOTO})' and rows.url.params['item_id'] == 'is.null'


def test_discard_keeps_the_row_when_the_file_delete_fails(client):
    fake = use(client, FakeSupabase([(200, [{'photo_id': PHOTO, 'storage_path': PATH}]), (503, {'message': 'down'})]))
    r = client.post(f'/api/intake/jobs/{JOB}/discard', headers=AUTH)
    assert r.status_code == 502 and 'discard again' in r.json()['detail']['message']
    assert len(fake.calls) == 2


@pytest.mark.parametrize('code,status', [('PT404', 404), ('PT409', 409)])
def test_discard_refusals_pass_through(client, code, status):
    use(client, FakeSupabase([(status, {'code': code, 'message': 'nope'})]))
    assert client.post(f'/api/intake/jobs/{JOB}/discard', headers=AUTH).status_code == status


def test_retry(client):
    fake = use(client, FakeSupabase([(200, [{'id': JOB}]), (200, [job_row('queued')]), SIGNED]))
    r = client.post(f'/api/intake/jobs/{JOB}/retry', headers=AUTH)
    assert r.status_code == 200 and r.json()['status'] == 'queued'
    assert fake.calls[0].url.path.endswith('/rpc/retry_intake_job')
    use(client, FakeSupabase([(429, {'code': 'PT429', 'message': 'Daily limit of 200 photos reached'})]))
    assert client.post(f'/api/intake/jobs/{JOB}/retry', headers=AUTH).status_code == 429


# --- create with an occasion, open list -------------------------------------------------------------------

def test_create_passes_the_batch_occasion(client):
    fake = use(client, FakeSupabase([(200, [{'id': JOB}]), (200, [job_row('queued')]), SIGNED]))
    r = client.post('/api/intake/jobs', headers=AUTH, json={'photo_ids': [PHOTO], 'mode': 'single', 'occasion_id': OCC})
    assert r.status_code == 201
    assert json.loads(fake.calls[0].content)['p_occasion_id'] == OCC
    assert r.json()[0]['photo']['url']


def test_open_list_asks_for_unfinished_jobs_only(client):
    fake = use(client, FakeSupabase([(200, [])]))
    client.get('/api/intake/jobs?open=true', headers=AUTH)
    assert fake.calls[0].url.params['status'] == 'in.(queued,processing,needs_review,failed)'
    assert client.get('/api/intake/jobs?open=true&status=done', headers=AUTH).status_code == 422


def test_list_still_works_when_signing_fails(client):
    use(client, FakeSupabase([(200, [job_row()]), (503, {'message': 'down'})]))
    r = client.get('/api/intake/jobs', headers=AUTH)
    assert r.status_code == 200 and r.json()[0]['photo']['url'] is None


# --- occasions and items ----------------------------------------------------------------------------------

def test_occasions(client):
    fake = use(client, FakeSupabase([(200, []), (201, [{'id': OCC, 'name': 'Christmas 2025', 'owner_id': USER_A}])]))
    client.get('/api/occasions', headers=AUTH)
    assert fake.calls[0].url.params['order'] == 'occurred_on.desc.nullslast,created_at.desc'
    r = client.post('/api/occasions', headers=AUTH, json={'name': ' Christmas 2025 ', 'occurred_on': '2025-12-25'})
    assert r.status_code == 201 and 'owner_id' not in r.json()
    assert json.loads(fake.calls[1].content) == {'name': 'Christmas 2025', 'kind': 'other', 'occurred_on': '2025-12-25',
                                                 'date_is_approximate': False}
    for bad in ({'name': ''}, {'name': 'x', 'owner_id': USER_A}, {'name': 'x', 'kind': 'party'}):
        assert client.post('/api/occasions', headers=AUTH, json=bad).status_code == 422


def test_sealed_can_be_not_recorded(client):
    fake = use(client, FakeSupabase([(201, [{'id': 'i1'}]), (200, [{'id': 'i1', 'version': 2}])]))
    assert client.post('/api/items', headers=AUTH, json={'name': 'x', 'category_id': CAT}).status_code == 201
    assert json.loads(fake.calls[0].content)['sealed'] is None
    assert client.patch(f'/api/items/{JOB}', headers=AUTH, json={'version': 1, 'sealed': None}).status_code == 200
    assert json.loads(fake.calls[1].content) == {'sealed': None}


# --- the fake model ---------------------------------------------------------------------------------------

def image_content(colour) -> list[dict]:
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), colour).save(buf, 'JPEG')
    return [{'type': 'input_text', 'text': 'x'},
            {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()}]


@pytest.mark.parametrize('colour,name', [((220, 30, 30), 'Zelda'), ((30, 200, 30), 'Spirited'), ((30, 30, 220), 'mug')])
def test_fake_model_answers_by_colour_with_valid_cards(colour, name):
    card, usage = asyncio.run(FakeAIClient().parse(MODES['single'], '', image_content(colour), CATEGORIES.card))
    assert name in card.name and usage['cost_usd'] == 0
    assert card.category in CATEGORIES.ids  # falls back to a category that exists


def test_fake_model_group_and_failure():
    scene, _ = asyncio.run(FakeAIClient().parse(MODES['group'], '', image_content((120, 120, 120)), Scene))
    assert len(scene.items) == 6 and scene.visible_but_unidentifiable == 2
    with pytest.raises(AIError):
        asyncio.run(FakeAIClient().parse(MODES['single'], '', image_content((0, 0, 0)), CATEGORIES.card))
