"""S12 in the database: one work per catalog entry, user-created releases with the duplicate check under a lock,
work links that are never overwritten, and created_by hidden from users.

Vectors are made here (a random direction per test, and points at a chosen cosine distance from it), so the
check is tested against real pgvector math without calling OpenAI.
"""
import math
import random
import threading
import uuid

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import as_role, connect, random_upc

MAX = 0.028   # the backend's DUPLICATE_MAX_DISTANCE (docs/DUPLICATE_THRESHOLD.md)


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def direction():
    return unit([random.gauss(0, 1) for _ in range(512)])


def at_distance(base, d):
    """A unit vector whose cosine distance from `base` is d."""
    other = direction()
    dot = sum(a * b for a, b in zip(base, other))
    ortho = unit([o - dot * b for o, b in zip(other, base)])
    c = 1 - d
    s = math.sqrt(max(0.0, 1 - c * c))
    return [c * b + s * o for b, o in zip(base, ortho)]


def vtext(v):
    return '[' + ','.join(f'{x:.7g}' for x in v) + ']'


@pytest.fixture
def made(admin):
    """Release and work ids made by a test, removed afterwards (created_by is set null when users go, not deleted)."""
    ids = {'releases': [], 'works': [], 'refs': []}
    yield ids
    admin.execute('delete from releases where id = any(%s)', (ids['releases'],))
    admin.execute('delete from works where id = any(%s) or catalog_ref = any(%s)', (ids['works'], ids['refs']))


def create(conn, made, title, vector=None, *, fmt=None, edition=None, barcode=None, work_id=None, new_work=None,
           user=None, declined=()):
    out = conn.execute(
        'select create_user_release(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
        (title, fmt, edition, barcode, vtext(vector) if vector else None, work_id,
         Jsonb(new_work) if new_work else None, user, MAX, list(declined)),
    ).fetchone()[0]
    if out['release']:
        made['releases'].append(out['release']['id'])
    return out


def work_of(admin, release_id):
    row = admin.execute('select w.id, w.title, w.year, w.kind, w.catalog_ref from release_works rw '
                        'join works w on w.id = rw.work_id where rw.release_id = %s', (release_id,)).fetchone()
    return row


def ref():
    return f'tmdb_movie:{random.randint(10**8, 10**9)}'


# --- work_from_catalog() ------------------------------------------------------------------------------------------

def from_catalog(conn, r, title, user, year=1997):
    return conn.execute('select work_from_catalog(%s, %s, %s, %s, %s, %s)',
                        (r, title, year, 'movie', Jsonb({'tmdb_movie': r.split(':', 1)[1]}), user)).fetchone()[0]


def test_two_users_linking_one_film_at_once_get_one_work(make_user, made, admin):
    a, b = make_user('a'), make_user('b')
    r = ref()
    made['refs'].append(r)
    out = {}
    with connect() as conn_a, connect() as conn_b:
        with as_role(conn_a, 'service_role'):
            out['a'] = from_catalog(conn_a, r, 'Princess Mononoke', a)

            def link_b():
                with as_role(conn_b, 'service_role'):
                    out['b'] = from_catalog(conn_b, r, 'Something else', b)

            t = threading.Thread(target=link_b)
            t.start()
            t.join(timeout=1)
            assert t.is_alive(), "B waits on A's uncommitted work"
        t.join(timeout=10)
    assert out['a']['created'] and not out['b']['created'] and out['a']['id'] == out['b']['id']
    assert 'created_by' not in out['a']
    rows = admin.execute('select title, created_by from works where catalog_ref = %s', (r,)).fetchall()
    assert rows == [('Princess Mononoke', a)]        # the first answer stands; B's title never landed


def test_catalog_ref_must_look_like_one(admin):
    with connect() as conn, pytest.raises(errors.CheckViolation):
        with as_role(conn, 'service_role'):
            from_catalog(conn, 'tmdb_movie:1; drop table works', 'x', None)


# --- created_by and the embedding are backend only ----------------------------------------------------------------

@pytest.mark.parametrize('sql', [
    'select created_by from releases', 'select embedding from releases', 'select * from releases',
    'select created_by from works', 'select * from works',
])
def test_users_cannot_read_who_created_shared_rows(make_user, sql):
    u = make_user('u')
    with connect() as conn, pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, 'authenticated', u):
            conn.execute(sql + ' limit 1')


def test_users_still_read_the_catalog_columns(make_user, made, admin):
    u = make_user('u')
    with connect() as conn, as_role(conn, 'service_role'):
        rel = create(conn, made, 'Readable', direction(), fmt='DVD', user=u,
                     new_work={'title': 'Readable', 'year': 2001, 'kind': 'movie'})['release']
    assert 'created_by' not in rel and 'embedding' not in rel
    with connect() as conn, as_role(conn, 'authenticated', u):
        row = conn.execute('select id, barcode, title, edition, format, release_year, verified, attributes '
                           'from releases where id = %s', (rel['id'],)).fetchone()
        assert row[2] == 'Readable' and row[7] == {'source': 'user'}
        work = conn.execute('select w.title, w.year, w.kind, w.catalog_ref from release_works rw join works w '
                            'on w.id = rw.work_id where rw.release_id = %s', (rel['id'],)).fetchone()
        assert work == ('Readable', 2001, 'movie', None)
    made['works'].append(work_of(admin, rel['id'])[0])


@pytest.mark.parametrize('sql', [
    "select work_from_catalog('tmdb_movie:1', 'x', 1, 'movie', '{}', null)",
    "select create_user_release('x', null, null, null, null, null, null, null, 0.1, '{}')",
    "select * from similar_releases('[1]', null, 0.1, 3)",
    "select link_release_work(gen_random_uuid(), gen_random_uuid())",
    "insert into works (title, kind) values ('x', 'movie')",
    "insert into release_works (release_id, work_id) values (gen_random_uuid(), gen_random_uuid())",
])
def test_users_cannot_write_the_catalog(make_user, sql):
    u = make_user('u')
    with connect() as conn, pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, 'authenticated', u):
            conn.execute(sql)


# --- create_user_release() and the duplicate check ----------------------------------------------------------------

def test_new_release_and_new_work_from_the_approved_fields(make_user, made, admin):
    u = make_user('u')
    with connect() as conn, as_role(conn, 'service_role'):
        out = create(conn, made, '  Spirited Away  ', direction(), fmt='Blu-ray', edition='Steelbook', user=u,
                     new_work={'title': 'Spirited Away', 'year': 2001, 'kind': 'movie'})
    assert out['status'] == 'created' and out['similar'] == []
    row = admin.execute('select title, format, edition, barcode, attributes, created_by, verified, embedding is not null '
                        'from releases where id = %s', (out['release']['id'],)).fetchone()
    assert row == ('Spirited Away', 'Blu-ray', 'Steelbook', None, {'source': 'user'}, u, False, True)
    work = work_of(admin, out['release']['id'])
    made['works'].append(work[0])
    assert work[1:] == ('Spirited Away', 2001, 'movie', None)


def test_a_near_identical_release_is_offered_and_nothing_is_made(make_user, made, admin):
    u = make_user('u')
    base = direction()
    with connect() as conn, as_role(conn, 'service_role'):
        first = create(conn, made, 'Spirited Away', base, fmt='Blu-ray', user=u)['release']
        out = create(conn, made, 'spirited away', at_distance(base, 0.01), fmt='Blu-ray', user=u,
                     new_work={'title': 'Spirited Away', 'year': 2001, 'kind': 'movie'})
    assert out['status'] == 'similar' and out['release'] is None
    assert [s['id'] for s in out['similar']] == [first['id']] and abs(out['similar'][0]['distance'] - 0.01) < 1e-4
    assert admin.execute("select count(*) from works where title = 'Spirited Away' and catalog_ref is null "
                         "and created_by = %s", (u,)).fetchone()[0] == 0       # no orphan work either


def test_declined_suggestions_are_not_offered_again(make_user, made):
    u = make_user('u')
    base = direction()
    with connect() as conn, as_role(conn, 'service_role'):
        first = create(conn, made, 'Spirited Away', base, fmt='Blu-ray', user=u)['release']
        out = create(conn, made, 'Spirited Away', at_distance(base, 0.01), fmt='Blu-ray', user=u, declined=[first['id']])
    assert out['status'] == 'created'


@pytest.mark.parametrize('distance, fmt_b, status', [
    (0.020, 'Blu-ray', 'similar'),     # under the threshold, same format
    (0.020, None, 'similar'),          # format unknown on one side: still offered
    (0.035, 'Blu-ray', 'created'),     # over the threshold
    (0.005, 'DVD', 'created'),         # another format is never a duplicate, however close
])
def test_threshold_and_format_rule(make_user, made, distance, fmt_b, status):
    u = make_user('u')
    base = direction()
    with connect() as conn, as_role(conn, 'service_role'):
        create(conn, made, 'Nausicaa', base, fmt='Blu-ray', user=u)
        assert create(conn, made, 'Nausicaa', at_distance(base, distance), fmt=fmt_b, user=u)['status'] == status


def test_two_people_creating_one_release_at_once(make_user, made, admin):
    """A's create holds the lock, uncommitted. B's waits, then re-checks and is offered A's release: no twin."""
    a, b = make_user('a'), make_user('b')
    base = direction()
    out = {}
    with connect() as conn_a, connect() as conn_b:
        with as_role(conn_a, 'service_role'):
            out['a'] = create(conn_a, made, 'Howl’s Moving Castle', base, fmt='DVD', user=a)

            def create_b():
                with as_role(conn_b, 'service_role'):
                    out['b'] = create(conn_b, made, 'Howls Moving Castle', at_distance(base, 0.015), fmt='DVD', user=b)

            t = threading.Thread(target=create_b)
            t.start()
            t.join(timeout=1)
            assert t.is_alive(), "B waits for A's lock"
        t.join(timeout=10)
    assert out['a']['status'] == 'created'
    assert out['b']['status'] == 'similar' and out['b']['similar'][0]['id'] == out['a']['release']['id']
    assert admin.execute('select count(*) from releases where id = any(%s)', (made['releases'],)).fetchone()[0] == 1


def test_one_barcode_one_release_and_it_is_not_changed(make_user, made, admin):
    a, b = make_user('a'), make_user('b')
    code = '0' + random_upc()
    with connect() as conn, as_role(conn, 'service_role'):
        first = create(conn, made, 'From A', direction(), fmt='Blu-ray', barcode=code, user=a)
        second = create(conn, made, 'From B', direction(), fmt='DVD', edition='Steelbook', barcode=code[1:], user=b)
    assert first['status'] == 'created' and second['status'] == 'existing'
    assert second['release']['id'] == first['release']['id']
    assert admin.execute('select title, format, edition, created_by from releases where barcode = %s',
                         (code,)).fetchone() == ('From A', 'Blu-ray', None, a)


def test_user_works_with_the_same_title_kind_and_year_are_reused(make_user, made, admin):
    u = make_user('u')
    title = f'Obscure film {uuid.uuid4().hex[:6]}'
    with connect() as conn, as_role(conn, 'service_role'):
        r1 = create(conn, made, title, direction(), fmt='DVD', user=u, new_work={'title': title, 'year': 1990, 'kind': 'movie'})
        r2 = create(conn, made, title, direction(), fmt='Blu-ray', user=u, new_work={'title': title.upper(), 'year': 1990, 'kind': 'movie'})
        r3 = create(conn, made, title, direction(), fmt='VHS', user=u, new_work={'title': title, 'year': 2020, 'kind': 'movie'})
    w1, w2, w3 = (work_of(admin, r['release']['id'])[0] for r in (r1, r2, r3))
    made['works'] += [w1, w3]
    assert w1 == w2 and w1 != w3


def test_bad_input_is_refused(make_user, made):
    u = make_user('u')
    with connect() as conn:
        for kwargs in ({'title': '   '}, {'title': 'x', 'work_id': uuid.uuid4(), 'new_work': {'title': 'x', 'kind': 'movie'}},
                       {'title': 'x', 'new_work': {'title': ' ', 'kind': 'movie'}}):
            with pytest.raises(errors.InvalidParameterValue):
                with as_role(conn, 'service_role'):
                    create(conn, made, kwargs.pop('title'), user=u, **kwargs)
        with pytest.raises(errors.CheckViolation):
            with as_role(conn, 'service_role'):
                create(conn, made, 'x', user=u, new_work={'title': 'x', 'kind': 'podcast'})


# --- link_release_work() ------------------------------------------------------------------------------------------

def test_a_release_gets_one_work_and_keeps_it(make_user, made, admin):
    u = make_user('u')
    r1, r2 = ref(), ref()
    made['refs'] += [r1, r2]
    with connect() as conn, as_role(conn, 'service_role'):
        rel = create(conn, made, 'Barcode release', direction(), barcode='0' + random_upc(), user=u)['release']
        w1 = from_catalog(conn, r1, 'Right film', u)
        w2 = from_catalog(conn, r2, 'Other film', u)
        first = conn.execute('select link_release_work(%s, %s)', (rel['id'], w1['id'])).fetchone()[0]
        second = conn.execute('select link_release_work(%s, %s)', (rel['id'], w2['id'])).fetchone()[0]
    assert first == {'work_id': w1['id'], 'linked': True}
    assert second == {'work_id': w1['id'], 'linked': False}
    assert work_of(admin, rel['id'])[1] == 'Right film'


def test_two_people_linking_one_release_at_once(make_user, made, admin):
    a, b = make_user('a'), make_user('b')
    r1, r2 = ref(), ref()
    made['refs'] += [r1, r2]
    with connect() as conn, as_role(conn, 'service_role'):
        rel = create(conn, made, 'Contested', direction(), barcode='0' + random_upc(), user=a)['release']
        w1, w2 = from_catalog(conn, r1, 'One', a)['id'], from_catalog(conn, r2, 'Two', b)['id']
    out = {}
    with connect() as conn_a, connect() as conn_b:
        with as_role(conn_a, 'service_role'):
            out['a'] = conn_a.execute('select link_release_work(%s, %s)', (rel['id'], w1)).fetchone()[0]

            def link_b():
                with as_role(conn_b, 'service_role'):
                    out['b'] = conn_b.execute('select link_release_work(%s, %s)', (rel['id'], w2)).fetchone()[0]

            t = threading.Thread(target=link_b)
            t.start()
            t.join(timeout=1)
            assert t.is_alive(), "B waits on A's lock on the release row"
        t.join(timeout=10)
    assert out['a']['linked'] and not out['b']['linked'] and out['b']['work_id'] == w1
    assert admin.execute('select count(*) from release_works where release_id = %s', (rel['id'],)).fetchone()[0] == 1


def test_unknown_release_is_404(make_user):
    with connect() as conn, pytest.raises(psycopg.Error) as e:
        with as_role(conn, 'service_role'):
            conn.execute('select link_release_work(%s, %s)', (uuid.uuid4(), uuid.uuid4()))
    assert e.value.sqlstate == 'PT404'
