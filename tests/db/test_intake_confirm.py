"""confirm_intake_job(), discard_intake_job(), retry_intake_job() and batch occasions (S10), against the real policies.

Called the way the API calls them: as role authenticated with the user's JWT claims, so auth.uid() is the caller.
"""
import json
import threading
import uuid

import psycopg
import pytest

from conftest import as_role, connect
from test_intake_jobs import create, photo


def call(user, sql, params=()):
    with connect() as conn, as_role(conn, 'authenticated', user):
        return conn.execute(sql, params).fetchall()


def sqlstate(user, sql, params=()) -> str:
    with pytest.raises(psycopg.Error) as e:
        call(user, sql, params)
    return e.value.sqlstate


def confirm(user, job, items, copies=()):
    return call(user, 'select id, name, owner_id, intake_job_id, sealed from confirm_intake_job(%s, %s, %s)',
                (job, json.dumps(items), json.dumps(list(copies))))


def copy_of(owner) -> dict:
    cid = uuid.uuid4()
    return {'id': str(cid), 'storage_path': f'{owner}/{cid}.jpg'}


@pytest.fixture
def two_users(make_user):
    return make_user('a'), make_user('b')


@pytest.fixture
def ready_job(admin):
    """A job of `owner` whose card is waiting for review; returns (job id, photo id)."""
    def _make(owner, mode='single', status='needs_review'):
        p = photo(admin, owner, width=2048, height=1536)
        job = create(owner, [p], mode)[0][0]
        admin.execute("update intake_jobs set status = %s, card = '{\"name\": \"x\"}' where id = %s", (status, job))
        return job, p
    return _make


def item(category_id, name='Zelda', **extra):
    return {'name': name, 'category_id': str(category_id), **extra}


def test_confirm_single_creates_item_links_photo_and_finishes_job(admin, two_users, ready_job, category_id):
    a, _ = two_users
    job, p = ready_job(a)
    rows = confirm(a, job, [item(category_id, sealed=None, attributes={'platform': 'Switch'})])
    assert len(rows) == 1
    iid, name, owner, from_job, sealed = rows[0]
    assert (name, owner, from_job, sealed) == ('Zelda', a, job, None)  # sealed may be "not recorded"
    assert admin.execute('select item_id from photos where id = %s', (p,)).fetchone()[0] == iid
    assert admin.execute('select status, item_id from intake_jobs where id = %s', (job,)).fetchone() == ('done', iid)
    assert admin.execute('select attributes from items where id = %s', (iid,)).fetchone()[0] == {'platform': 'Switch'}


def test_owner_comes_from_the_token_not_the_payload(admin, two_users, ready_job, category_id):
    a, b = two_users
    job, _ = ready_job(a)
    rows = confirm(a, job, [item(category_id, owner_id=str(b), id=str(uuid.uuid4()), version=99)])
    assert rows[0][2] == a
    assert admin.execute('select version from items where id = %s', (rows[0][0],)).fetchone()[0] == 1


def test_group_confirm_of_selected_rows_gives_each_item_a_photo(admin, two_users, ready_job, category_id):
    a, _ = two_users
    job, p = ready_job(a, 'group')
    copies = [copy_of(a), copy_of(a)]
    rows = confirm(a, job, [item(category_id, 'One'), item(category_id, 'Two'), item(category_id, 'Three')], copies)
    ids = [r[0] for r in rows]
    assert [r[1] for r in rows] == ['One', 'Two', 'Three']
    photos = admin.execute('select id, item_id, storage_path, width, height, intake_job_id from photos '
                           'where intake_job_id = %s order by storage_path', (job,)).fetchall()
    by_item = {r[1]: r for r in photos}
    assert set(by_item) == set(ids)
    assert by_item[ids[0]][0] == p                                         # the original goes to the first item
    assert {by_item[i][2] for i in ids[1:]} == {c['storage_path'] for c in copies}
    assert all(r[3:5] == (2048, 1536) for r in photos)                       # size copied from the original row
    assert admin.execute('select status, item_id from intake_jobs where id = %s', (job,)).fetchone() == ('done', ids[0])


def test_confirming_twice_is_409_and_creates_nothing_more(admin, two_users, ready_job, category_id):
    a, _ = two_users
    job, _ = ready_job(a)
    confirm(a, job, [item(category_id)])
    assert sqlstate(a, 'select confirm_intake_job(%s, %s)', (job, json.dumps([item(category_id)]))) == 'PT409'
    assert admin.execute('select count(*) from items where intake_job_id = %s', (job,)).fetchone()[0] == 1


def test_two_tabs_confirming_at_once_save_once(admin, two_users, ready_job, category_id):
    """Both transactions start together; the job row lock makes the second wait, then see 'done'."""
    a, _ = two_users
    job, _ = ready_job(a, 'group')
    barrier = threading.Barrier(2)
    results = []

    def tab(name):
        try:
            with connect() as conn, as_role(conn, 'authenticated', a):
                barrier.wait()
                conn.execute('select confirm_intake_job(%s, %s, %s)',
                             (job, json.dumps([item(category_id, name), item(category_id, name + '2')]),
                              json.dumps([copy_of(a)])))
                results.append('ok')
        except psycopg.Error as e:
            results.append(e.sqlstate)

    threads = [threading.Thread(target=tab, args=(n,)) for n in ('left', 'right')]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(results) == ['PT409', 'ok']
    assert admin.execute('select count(*) from items where intake_job_id = %s', (job,)).fetchone()[0] == 2


def test_another_users_job_is_not_found(admin, two_users, ready_job, category_id):
    a, b = two_users
    job, p = ready_job(a)
    assert sqlstate(b, 'select confirm_intake_job(%s, %s)', (job, json.dumps([item(category_id)]))) == 'PT404'
    assert sqlstate(b, 'select * from discard_intake_job(%s)', (job,)) == 'PT404'
    admin.execute("update intake_jobs set status = 'failed' where id = %s", (job,))
    assert sqlstate(b, 'select retry_intake_job(%s)', (job,)) == 'PT404'
    assert admin.execute('select status from intake_jobs where id = %s', (job,)).fetchone()[0] == 'failed'
    assert admin.execute('select item_id from photos where id = %s', (p,)).fetchone()[0] is None


def test_a_bad_item_rolls_back_the_whole_confirm(admin, two_users, ready_job, category_id):
    a, b = two_users
    job, p = ready_job(a, 'group')
    theirs = admin.execute("insert into categories (owner_id, name) values (%s, 'B only') returning id", (b,)).fetchone()[0]
    assert sqlstate(a, 'select confirm_intake_job(%s, %s, %s)',
                    (job, json.dumps([item(category_id, 'fine'), item(theirs, 'bad')]), json.dumps([copy_of(a)]))) == 'PT422'
    # A table check failing halfway (blank name on the second item) rolls back the first item too.
    assert sqlstate(a, 'select confirm_intake_job(%s, %s, %s)',
                    (job, json.dumps([item(category_id, 'fine'), item(category_id, '  ')]), json.dumps([copy_of(a)]))) == '23514'
    assert admin.execute('select count(*) from items where owner_id = %s', (a,)).fetchone()[0] == 0
    assert admin.execute('select count(*) from photos where intake_job_id = %s', (job,)).fetchone()[0] == 1
    assert admin.execute('select item_id from photos where id = %s', (p,)).fetchone()[0] is None
    assert admin.execute('select status from intake_jobs where id = %s', (job,)).fetchone()[0] == 'needs_review'


def test_links_must_be_the_callers_own(admin, two_users, ready_job, category_id):
    a, b = two_users
    job, _ = ready_job(a)
    their_occasion = admin.execute("insert into occasions (owner_id, name) values (%s, 'Theirs') returning id", (b,)).fetchone()[0]
    assert sqlstate(a, 'select confirm_intake_job(%s, %s)',
                    (job, json.dumps([item(category_id, occasion_id=str(their_occasion))]))) == '23503'
    assert admin.execute('select status from intake_jobs where id = %s', (job,)).fetchone()[0] == 'needs_review'


def test_photo_copies_are_checked(admin, two_users, ready_job, category_id):
    a, b = two_users
    job, _ = ready_job(a, 'group')
    two = json.dumps([item(category_id, 'One'), item(category_id, 'Two')])
    assert sqlstate(a, 'select confirm_intake_job(%s, %s, %s)', (job, two, '[]')) == '22023'
    assert sqlstate(a, 'select confirm_intake_job(%s, %s, %s)', (job, two, json.dumps([copy_of(b)]))) == '42501'
    assert sqlstate(a, 'select confirm_intake_job(%s, %s)', (job, '[]')) == '22023'
    assert sqlstate(a, 'select confirm_intake_job(%s, %s)', (job, json.dumps([item(category_id)] * 101))) == '22023'


def test_only_reviewable_or_failed_jobs_confirm(admin, two_users, ready_job, category_id):
    a, _ = two_users
    one = json.dumps([item(category_id)])
    for status in ('queued', 'processing', 'discarded'):
        job, _ = ready_job(a, status=status)
        assert sqlstate(a, 'select confirm_intake_job(%s, %s)', (job, one)) == 'PT409'
    job, _ = ready_job(a, status='failed')      # "add by hand" after the AI gave up
    assert len(confirm(a, job, [item(category_id, 'By hand')])) == 1


def test_discard(admin, two_users, ready_job, category_id):
    a, _ = two_users
    job, p = ready_job(a)
    assert call(a, 'select photo_id from discard_intake_job(%s)', (job,)) == [(p,)]
    assert admin.execute('select status, card from intake_jobs where id = %s', (job,)).fetchone() == ('discarded', {'name': 'x'})
    assert call(a, 'select photo_id from discard_intake_job(%s)', (job,)) == [(p,)]  # again: finish a half-done cleanup
    admin.execute('delete from photos where id = %s', (p,))
    assert call(a, 'select photo_id from discard_intake_job(%s)', (job,)) == []

    done, _ = ready_job(a)
    confirm(a, done, [item(category_id)])
    assert sqlstate(a, 'select * from discard_intake_job(%s)', (done,)) == 'PT409'
    busy, _ = ready_job(a, status='processing')
    assert sqlstate(a, 'select * from discard_intake_job(%s)', (busy,)) == 'PT409'
    queued, _ = ready_job(a, status='queued')
    call(a, 'select * from discard_intake_job(%s)', (queued,))   # before the worker got to it: never claimed now
    assert admin.execute('select status from intake_jobs where id = %s', (queued,)).fetchone()[0] == 'discarded'


def test_retry_requeues_a_failed_job_and_counts_toward_the_limit(admin, two_users, ready_job):
    a, _ = two_users
    job, _ = ready_job(a, status='failed')
    admin.execute("update intake_jobs set attempts = 3, error = 'boom' where id = %s", (job,))
    row = call(a, 'select status, attempts, error, card from retry_intake_job(%s)', (job,))[0]
    assert row == ('queued', 0, None, None)
    assert sqlstate(a, 'select retry_intake_job(%s)', (job,)) == 'PT409'   # only failed jobs
    with connect() as conn:
        assert conn.execute('select intake_photos_today(%s)', (a,)).fetchone()[0] == 2  # created + retried

    admin.execute('insert into intake_jobs (owner_id) select %s from generate_series(1, 198)', (a,))
    admin.execute("update intake_jobs set status = 'failed' where id = %s", (job,))
    assert sqlstate(a, 'select retry_intake_job(%s)', (job,)) == 'PT429'


def test_retry_without_a_photo_is_409(admin, two_users, ready_job):
    a, _ = two_users
    job, p = ready_job(a, status='failed')
    admin.execute('delete from photos where id = %s', (p,))
    assert sqlstate(a, 'select retry_intake_job(%s)', (job,)) == 'PT409'


def test_batch_occasion(admin, two_users):
    a, b = two_users
    mine = admin.execute("insert into occasions (owner_id, name) values (%s, 'Christmas 2025') returning id", (a,)).fetchone()[0]
    theirs = admin.execute("insert into occasions (owner_id, name) values (%s, 'Theirs') returning id", (b,)).fetchone()[0]
    p1, p2 = photo(admin, a), photo(admin, a)
    jobs = call(a, 'select id, occasion_id from create_intake_jobs(%s, %s, %s)', ([p1, p2], 'single', mine))
    assert [j[1] for j in jobs] == [mine, mine]
    p3 = photo(admin, a)
    assert sqlstate(a, 'select create_intake_jobs(%s, %s, %s)', ([p3], 'single', theirs)) == 'PT404'
    assert create(a, [p3])[0][0]  # the occasion stays optional


def test_helpers_are_not_callable_by_users(two_users, ready_job):
    a, _ = two_users
    job, _ = ready_job(a)
    assert sqlstate(a, 'select lock_own_intake_job(%s)', (job,)) == '42501'
    assert sqlstate(a, 'select intake_photos_today(%s)', (a,)) == '42501'
