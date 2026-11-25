"""create_intake_jobs() and fail_stale_intake_jobs() against the real policies (S9).

The API creates jobs by calling create_intake_jobs() with the user's token; these tests call it the same way
(role authenticated + JWT claims), so ownership, the daily limit and RLS are exercised for real.
"""
import uuid

import psycopg
import pytest

from conftest import as_role, connect


def photo(admin, owner: uuid.UUID, **cols) -> uuid.UUID:
    pid = uuid.uuid4()
    names = ['id', 'owner_id', 'storage_path', *cols]
    values = [pid, owner, f'{owner}/{pid}.jpg', *cols.values()]
    admin.execute(f'insert into photos ({", ".join(names)}) values ({", ".join(["%s"] * len(names))})', values)
    return pid


def create(user: uuid.UUID, photo_ids: list, mode: str = 'single') -> list[tuple]:
    with connect() as conn, as_role(conn, 'authenticated', user):
        return conn.execute('select id, owner_id, mode, status from create_intake_jobs(%s, %s)',
                            (photo_ids, mode)).fetchall()


def sqlstate_of(user, photo_ids, mode='single') -> str:
    with pytest.raises(psycopg.Error) as e:
        create(user, photo_ids, mode)
    return e.value.sqlstate


@pytest.fixture
def two_users(make_user):
    return make_user('a'), make_user('b')


def test_owner_queues_own_photos_one_job_each(admin, two_users):
    a, _ = two_users
    p1, p2 = photo(admin, a), photo(admin, a)
    jobs = create(a, [p2, p1, p2], 'group')  # a repeated id is queued once
    assert [(j[1], j[2], j[3]) for j in jobs] == [(a, 'group', 'queued')] * 2
    links = dict(admin.execute('select id, intake_job_id from photos where id = any(%s)', ([p1, p2],)).fetchall())
    assert [links[p2], links[p1]] == [j[0] for j in jobs]  # in the order given


def test_someone_elses_photo_is_not_found_and_nothing_is_created(admin, two_users):
    a, b = two_users
    theirs, mine = photo(admin, a), photo(admin, b)
    assert sqlstate_of(b, [mine, theirs]) == 'PT404'
    assert sqlstate_of(b, [uuid.uuid4()]) == 'PT404'
    assert admin.execute('select count(*) from intake_jobs where owner_id in (%s, %s)', (a, b)).fetchone()[0] == 0
    assert admin.execute('select count(*) from photos where intake_job_id is not null and id = any(%s)',
                         ([theirs, mine],)).fetchone()[0] == 0


def test_photo_on_an_item_or_already_queued_is_409(admin, two_users, category_id):
    a, _ = two_users
    item = admin.execute('insert into items (owner_id, category_id, name) values (%s, %s, %s) returning id',
                         (a, category_id, 'Zelda')).fetchone()[0]
    on_item, free = photo(admin, a, item_id=item), photo(admin, a)
    assert sqlstate_of(a, [on_item]) == 'PT409'
    create(a, [free])
    assert sqlstate_of(a, [free]) == 'PT409'


def test_bad_input_and_anon(admin, two_users):
    a, _ = two_users
    p = photo(admin, a)
    assert sqlstate_of(a, [p], 'shelf') == '22023'
    assert sqlstate_of(a, []) == '22023'
    assert sqlstate_of(a, [photo(admin, a) for _ in range(51)]) == '22023'
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as conn, as_role(conn, 'anon'):
        conn.execute('select create_intake_jobs(%s, %s)', ([p], 'single'))


def test_direct_insert_and_update_are_still_denied(admin, two_users):
    a, _ = two_users
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as conn, as_role(conn, 'authenticated', a):
        conn.execute("insert into intake_jobs (owner_id) values (%s)", (a,))
    job = create(a, [photo(admin, a)])[0][0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as conn, as_role(conn, 'authenticated', a):
        conn.execute("update intake_jobs set status = 'done', card = '{}' where id = %s", (job,))


def test_daily_limit(admin, two_users):
    a, b = two_users
    admin.execute('insert into intake_jobs (owner_id) select %s from generate_series(1, 199)', (a,))
    assert sqlstate_of(a, [photo(admin, a), photo(admin, a)]) == 'PT429'
    assert len(create(a, [photo(admin, a)])) == 1        # exactly at the limit is fine
    assert len(create(b, [photo(admin, b)])) == 1        # the limit is per user


def test_jobs_are_private(admin, two_users):
    a, b = two_users
    job = create(a, [photo(admin, a)])[0][0]
    with connect() as conn, as_role(conn, 'authenticated', b):
        assert conn.execute('select count(*) from intake_jobs where id = %s', (job,)).fetchone()[0] == 0
    with connect() as conn, as_role(conn, 'authenticated', a):
        assert conn.execute('select count(*) from intake_jobs where id = %s', (job,)).fetchone()[0] == 1


def test_stale_job_on_its_last_attempt_is_failed(admin, two_users):
    a, _ = two_users
    ids = [r[0] for r in admin.execute(
        'insert into intake_jobs (owner_id) select %s from generate_series(1, 3) returning id', (a,)).fetchall()]
    stale_last, stale_retryable, fresh_last = ids
    admin.execute("update intake_jobs set status = 'processing', locked_by = 'dead', "
                  "locked_at = now() - interval '10 minutes', attempts = 3 where id = %s", (stale_last,))
    admin.execute("update intake_jobs set status = 'processing', locked_by = 'dead', "
                  "locked_at = now() - interval '10 minutes', attempts = 1 where id = %s", (stale_retryable,))
    admin.execute("update intake_jobs set status = 'processing', locked_by = 'alive', "
                  "locked_at = now(), attempts = 3 where id = %s", (fresh_last,))
    with connect() as conn, as_role(conn, 'service_role'):
        assert conn.execute("select fail_stale_intake_jobs('5 minutes')").fetchone()[0] == 1
    rows = dict((r[0], r[1:]) for r in admin.execute(
        'select id, status, locked_by, error from intake_jobs where id = any(%s)', (ids,)).fetchall())
    assert rows[stale_last][:2] == ('failed', None) and 'worker stopped' in rows[stale_last][2]
    assert rows[stale_retryable][0] == 'processing'   # claim_intake_job() retries this one
    assert rows[fresh_last][0] == 'processing'        # still within its lease
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as conn, as_role(conn, 'authenticated', a):
        conn.execute('select fail_stale_intake_jobs()')
