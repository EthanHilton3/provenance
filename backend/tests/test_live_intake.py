"""The intake queue end to end against the LOCAL Supabase stack, with a fake OpenAI (no network to OpenAI, no cost).

Real: the API, PostgREST, RLS, Storage, create_intake_jobs(), claim_intake_job() with SKIP LOCKED, leases and the
worker's scoped writes. Fake: only the model, which answers from FakeOpenAI in test_intake.py.

Opt in, local only (the worker claims ANY queued job, so this must never point at a real queue):
  export SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY from `npx supabase status -o env`
  (API_URL, ANON_KEY, SERVICE_ROLE_KEY), then  PROVENANCE_LIVE=1 pytest tests/test_live_intake.py
"""
import asyncio
import os
import time

import httpx
import pytest

import photo_images as P
from app.ai import OpenAIClient
from app.db import service_db
from app.storage import service_storage
from app.worker import Worker, load_categories
from test_intake import CARD, SCENE, FakeOpenAI, reply
from test_live_cloud import client, env, users  # noqa: F401 (fixtures)

pytestmark = pytest.mark.skipif(not os.environ.get('PROVENANCE_LIVE'), reason='set PROVENANCE_LIVE=1 to run')
DONE = {'needs_review', 'failed'}


@pytest.fixture(scope='module', autouse=True)
def local_only(env):
    if not env.supabase_url.startswith(('http://127.0.0.1', 'http://localhost')):
        pytest.skip('the intake worker test runs against local Supabase only')


@pytest.fixture(autouse=True)
def drained(local_only):
    """Empties the local queue before each test (before it queues anything), so claims see only this test's jobs."""
    async def drain():
        async with httpx.AsyncClient(timeout=30) as http:
            db = service_db(http)
            w = Worker(db, service_storage(http), FakeOpenAI().client(), await load_categories(db), name='drain')
            await w.run_forever(stop_when_idle=True)
    asyncio.run(drain())


@pytest.fixture
def upload(client, users):
    """Uploads unattached photos as user A; deletes them (file and row) afterwards."""
    a = users[0]
    made = []

    def _upload(n=1) -> list[str]:
        for _ in range(n):
            r = client.post('/api/photos', headers=a['headers'], files={'file': ('x.jpg', P.make('JPEG'), 'image/jpeg')})
            assert r.status_code == 201, r.text
            made.append(r.json()['id'])
        return made[-n:]

    yield _upload
    for pid in made:
        client.delete(f'/api/photos/{pid}', headers=a['headers'])


def queue(client, user, photo_ids, mode='single'):
    r = client.post('/api/intake/jobs', headers=user['headers'], json={'photo_ids': photo_ids, 'mode': mode})
    assert r.status_code == 201, r.text
    return [j['id'] for j in r.json()]


async def with_worker(scenario, fake: FakeOpenAI | None = None, **kw):
    """Runs `scenario(make_worker, db)` with real service-role DB and Storage clients and a fake model."""
    fake = fake or FakeOpenAI()
    async with httpx.AsyncClient(timeout=30) as http:
        db = service_db(http)
        categories = await load_categories(db)

        def make_worker(name, **more):
            return Worker(db, service_storage(http), fake.client(), categories, name=name, **{**kw, **more})

        return await scenario(make_worker, db)


async def jobs(db, ids) -> dict[str, dict]:
    rows = await db.select('intake_jobs', {'select': '*', 'id': f'in.({",".join(ids)})'})
    return {r['id']: r for r in rows}


async def settle(worker, db, ids, timeout=20):
    """run_once until every job is needs_review or failed (retries may wait out a short backoff)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(j['status'] in DONE for j in (await jobs(db, ids)).values()):
            return await jobs(db, ids)
        if not await worker.run_once():
            await asyncio.sleep(0.2)
    raise AssertionError(f'jobs did not settle: {await jobs(db, ids)}')


def test_single_and_group_end_to_end_and_other_users_see_nothing(client, users, upload):
    a, b = users
    p1, p2 = upload(2)
    # B cannot queue A's photo, and nothing is created or linked.
    r = client.post('/api/intake/jobs', headers=b['headers'], json={'photo_ids': [p1], 'mode': 'single'})
    assert r.status_code == 404 and client.get('/api/intake/jobs', headers=b['headers']).json() == []
    single, = queue(client, a, [p1], 'single')
    group, = queue(client, a, [p2], 'group')
    assert client.post('/api/intake/jobs', headers=a['headers'], json={'photo_ids': [p1], 'mode': 'single'}).status_code == 409

    queued = client.get(f'/api/intake/jobs/{single}', headers=a['headers']).json()
    assert queued['status'] == 'queued' and queued['photo_ids'] == [p1] and queued['card'] is None

    fake = FakeOpenAI((200, reply(CARD)), (200, reply(SCENE)))  # claim order is oldest first: single, then group
    async def scenario(make_worker, db):
        await make_worker('w1').run_forever(stop_when_idle=True)
    asyncio.run(with_worker(scenario, fake))
    assert [r['model'] for r in fake.requests] == ['gpt-6-luna', 'gpt-6-sol']

    got = {j['id']: j for j in client.get('/api/intake/jobs', headers=a['headers']).json()}
    assert got[single]['status'] == got[group]['status'] == 'needs_review'
    assert got[single]['card']['name'] == CARD['name'] and got[single]['card']['category_id']
    assert got[group]['card']['items'][0]['name'] == SCENE['items'][0]['name']
    assert 'usage' not in got[single] and 'locked_by' not in got[single]
    # The category id is a real built-in category.
    cats = {c['id'] for c in client.get('/api/categories', headers=a['headers']).json()}
    assert got[single]['card']['category_id'] in cats
    # B sees none of it.
    assert client.get(f'/api/intake/jobs/{single}', headers=b['headers']).status_code == 404
    assert client.get('/api/intake/jobs', headers=b['headers']).json() == []


def test_racing_workers_process_each_job_exactly_once(client, users, upload):
    n, workers = 12, 4
    ids = queue(client, users[0], upload(n))
    handled: list[tuple[str, str]] = []

    class Slow(FakeOpenAI):  # a little model latency so the workers' claims overlap
        def client(self):
            inner = super().client()

            async def parse(*args, **kw):
                await asyncio.sleep(0.05)
                return await OpenAIClient.parse(inner, *args, **kw)
            inner.parse = parse
            return inner

    async def scenario(make_worker, db):
        crew = [make_worker(f'race-{i}') for i in range(workers)]
        for w in crew:
            original = w.handle

            async def handle(job, w=w, original=original):
                handled.append((w.name, job['id']))
                await original(job)
            w.handle = handle
        await asyncio.gather(*(w.run_forever(stop_when_idle=True) for w in crew))
        return await jobs(db, ids)

    fake = Slow()
    rows = asyncio.run(with_worker(scenario, fake))
    by_job = [jid for _, jid in handled]
    assert sorted(by_job) == sorted(ids), 'every job handled exactly once'
    assert len(fake.requests) == n, 'one model call per job'
    assert all(r['status'] == 'needs_review' and r['attempts'] == 1 and r['usage']['calls'] == 1 for r in rows.values())
    assert len({w for w, _ in handled}) > 1, 'the workers really ran at the same time'


def test_a_crashed_workers_job_is_retried_after_the_lease(client, users, upload):
    jid, = queue(client, users[0], upload(1))

    async def scenario(make_worker, db):
        dead = await db.rpc('claim_intake_job', {'p_worker': 'crashed', 'p_lease': '1 seconds'})
        assert [j['id'] for j in dead] == [jid]           # claimed, then the "worker" never finishes
        w = make_worker('w2')
        assert await w.run_once() is False                # still inside the lease: nobody else may take it
        await asyncio.sleep(1.5)
        assert await w.run_once() is True                 # lease over: claimed again
        return (await jobs(db, [jid]))[jid]

    row = asyncio.run(with_worker(scenario, lease_seconds=1))
    assert row['status'] == 'needs_review' and row['attempts'] == 2 and row['locked_by'] is None


def test_a_late_worker_cannot_overwrite_the_result(client, users, upload):
    jid, = queue(client, users[0], upload(1))

    async def scenario(make_worker, db):
        claim = lambda name: db.rpc('claim_intake_job', {'p_worker': name, 'p_lease': '1 seconds'})
        stale = (await claim('slow'))[0]
        await asyncio.sleep(1.5)
        fresh = (await claim('fast'))[0]                   # lease over: reclaimed, and still being worked on
        assert fresh['id'] == jid and fresh['attempts'] == 2
        slow, fast = make_worker('slow'), make_worker('fast')
        during = await slow._write(stale, {'status': 'failed', 'error': 'late'})   # blocked by locked_by
        finished = await fast._write(fresh, {'status': 'needs_review', 'card': {'name': 'x'}, 'error': None})
        after = await slow._write(stale, {'status': 'failed', 'error': 'late'})    # blocked by status too
        return during, finished, after, (await jobs(db, [jid]))[jid]

    during, finished, after, row = asyncio.run(with_worker(scenario, lease_seconds=1))
    assert (during, finished, after) == (False, True, False)
    assert row['status'] == 'needs_review' and row['error'] is None and row['card'] == {'name': 'x'}


def test_invalid_output_is_retried_then_succeeds(client, users, upload):
    jid, = queue(client, users[0], upload(1))
    fake = FakeOpenAI((200, reply('{"item_count": 1, "cut off')), (200, reply(CARD)))

    async def scenario(make_worker, db):
        return (await settle(make_worker('w'), db, [jid]))[jid]

    row = asyncio.run(with_worker(scenario, fake, backoff_seconds=0.5))
    assert row['status'] == 'needs_review' and row['attempts'] == 2 and row['error'] is None
    assert row['usage']['calls'] == 2 and row['usage']['cost_usd'] > 0


def test_max_attempts_leads_to_failed_with_a_readable_reason(client, users, upload):
    jid, = queue(client, users[0], upload(1))
    fake = FakeOpenAI((200, reply({**CARD, 'category': 'Not a category'})))

    async def scenario(make_worker, db):
        return (await settle(make_worker('w'), db, [jid]))[jid]

    row = asyncio.run(with_worker(scenario, fake, backoff_seconds=0.2))
    assert row['status'] == 'failed' and row['attempts'] == row['max_attempts'] == 3
    assert row['error'] == "The AI's answer did not match the card format. Gave up after 3 tries."
    assert row['usage']['calls'] == 3 and len(fake.requests) == 3
    shown = client.get(f'/api/intake/jobs/{jid}', headers=users[0]['headers']).json()
    assert shown['status'] == 'failed' and shown['card'] is None and 'Gave up' in shown['error']


def test_a_crash_on_the_last_attempt_ends_failed_not_stuck(client, users, upload):
    jid, = queue(client, users[0], upload(1))

    async def scenario(make_worker, db):
        await db.update('intake_jobs', {'id': f'eq.{jid}'}, {'max_attempts': 1})
        await db.rpc('claim_intake_job', {'p_worker': 'crashed', 'p_lease': '1 seconds'})
        await asyncio.sleep(1.5)
        assert await make_worker('w').run_once() is False  # nothing to claim; the reaper ran first
        return (await jobs(db, [jid]))[jid]

    row = asyncio.run(with_worker(scenario, lease_seconds=1))
    assert row['status'] == 'failed' and 'worker stopped' in row['error'] and row['locked_by'] is None


# --- S10: confirm, discard, retry through the real API, Storage and database ----------------------------------

def work(fake=None, **kw):
    async def scenario(make_worker, db):
        await make_worker('s10').run_forever(stop_when_idle=True)
    asyncio.run(with_worker(scenario, fake, **kw))


def a_category(client, user, path=('Books', 'Manga')):
    rows = client.get('/api/categories', headers=user['headers']).json()
    parent = next(c for c in rows if c['name'] == path[0] and not c['parent_id'])
    return next(c for c in rows if c['name'] == path[1] and c['parent_id'] == parent['id'])['id']


def test_group_confirm_gives_each_item_its_own_photo_once(client, users, upload):
    a, b = users
    jid, = queue(client, a, upload(1), 'group')
    work(FakeOpenAI((200, reply(SCENE))))
    cat = a_category(client, a)
    body = {'items': [{'name': 'One Piece', 'category_id': cat, 'sealed': None, 'attributes': {'volume': '1-3'}},
                      {'name': 'Trigun Maximum', 'category_id': cat, 'sealed': False}]}

    assert client.post(f'/api/intake/jobs/{jid}/confirm', headers=b['headers'], json=body).status_code == 404
    r = client.post(f'/api/intake/jobs/{jid}/confirm', headers=a['headers'], json=body)
    assert r.status_code == 200, r.text
    items = r.json()['items']
    assert [i['name'] for i in items] == ['One Piece', 'Trigun Maximum'] and items[0]['sealed'] is None
    assert all(i['intake_job_id'] == jid for i in items) and r.json()['job']['status'] == 'done'
    try:
        # Each item has exactly one photo, and both files really exist (the copy was made in Storage).
        blobs = []
        for it in items:
            photos = client.get(f'/api/items/{it["id"]}/photos', headers=a['headers']).json()
            assert len(photos) == 1 and photos[0]['url']
            got = httpx.get(photos[0]['url'])
            assert got.status_code == 200 and got.content[:2] == b'\xff\xd8'
            blobs.append(got.content)
        assert blobs[0] == blobs[1]
        # Confirming again, from this or another tab, saves nothing more and says what was saved.
        again = client.post(f'/api/intake/jobs/{jid}/confirm', headers=a['headers'], json=body)
        assert again.status_code == 409
        assert {i['id'] for i in again.json()['detail']['job']['items']} == {i['id'] for i in items}
        mine = client.get('/api/items', headers=a['headers']).json()
        assert sum(1 for i in mine if i.get('intake_job_id') == jid) == 2
    finally:
        for it in items:  # deleting an item removes its own file; the other item's photo is untouched until its turn
            assert client.delete(f'/api/items/{it["id"]}', headers=a['headers']).status_code == 204


def test_discard_deletes_the_photo_and_keeps_the_job(client, users, upload):
    a, _ = users
    pid, = upload(1)
    jid, = queue(client, a, [pid])
    work()
    assert client.post(f'/api/intake/jobs/{jid}/discard', headers=a['headers']).status_code == 204
    job = client.get(f'/api/intake/jobs/{jid}', headers=a['headers']).json()
    assert job['status'] == 'discarded' and job['photo_ids'] == []
    assert client.post(f'/api/intake/jobs/{jid}/discard', headers=a['headers']).status_code == 204  # idempotent
    assert client.post(f'/api/intake/jobs/{jid}/confirm', headers=a['headers'],
                       json={'items': [{'name': 'x', 'category_id': a_category(client, a)}]}).status_code == 409

    async def file_gone():
        async with httpx.AsyncClient() as http:
            rows = await service_db(http).select('photos', {'select': 'id', 'id': f'eq.{pid}'})
            try:
                await service_storage(http).download(f'{a["id"]}/{pid}.jpg')
                return rows, False
            except Exception:  # noqa: BLE001 - any refusal means the file is not there
                return rows, True
    rows, gone = asyncio.run(file_gone())
    assert rows == [] and gone


def test_failed_job_can_be_retried_or_added_by_hand(client, users, upload):
    a, _ = users
    retry_me, by_hand = queue(client, a, upload(2))

    async def drain(make_worker, db):
        return await settle(make_worker('s10'), db, [retry_me, by_hand])
    asyncio.run(with_worker(drain, FakeOpenAI((200, reply('not json'))), backoff_seconds=0.1))
    for jid in (retry_me, by_hand):
        assert client.get(f'/api/intake/jobs/{jid}', headers=a['headers']).json()['status'] == 'failed'

    r = client.post(f'/api/intake/jobs/{retry_me}/retry', headers=a['headers'])
    assert r.status_code == 200 and r.json()['status'] == 'queued' and r.json()['attempts'] == 0
    work(FakeOpenAI((200, reply(CARD))))
    assert client.get(f'/api/intake/jobs/{retry_me}', headers=a['headers']).json()['status'] == 'needs_review'

    r = client.post(f'/api/intake/jobs/{by_hand}/confirm', headers=a['headers'],
                    json={'items': [{'name': 'Typed in by hand', 'category_id': a_category(client, a)}]})
    assert r.status_code == 200, r.text
    item = r.json()['items'][0]
    assert len(client.get(f'/api/items/{item["id"]}/photos', headers=a['headers']).json()) == 1
    client.delete(f'/api/items/{item["id"]}', headers=a['headers'])
    client.post(f'/api/intake/jobs/{retry_me}/discard', headers=a['headers'])
