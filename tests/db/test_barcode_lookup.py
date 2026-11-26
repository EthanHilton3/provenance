"""S11 barcode lookup in the database: check digits, release_from_catalog() (one release per barcode, never
overwritten, never writable by users), the shared UPC budget (begin_catalog_call()) and a barcode on an intake job.
"""
import threading
import uuid

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import as_role, connect, random_upc
from test_intake_jobs import photo


# --- check digits ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('code, ok', [
    ('036000291452', True), ('0036000291452', True), ('4006381333931', True), ('96385074', True),
    ('9780306406157', True), ('10012345000017', True),
    ('883929704736', True),          # LOTR 4K, from the barcode test
    ('045496900397', True),          # IMG_9427 as printed
    ('045496600397', False),         # IMG_9427 as the model misread it: one digit off
    ('036000291453', False), ('03600029145', False), ('03600029145a', False), ('', False),
])
def test_gtin_valid(admin, code, ok):
    assert admin.execute('select public.gtin_valid(%s)', (code,)).fetchone()[0] is ok


def test_release_with_a_bad_check_digit_is_refused():
    with connect() as conn, pytest.raises(errors.CheckViolation):
        with as_role(conn, 'service_role'):
            conn.execute("insert into releases (barcode, title) values ('045496600397', 'misread')")


# --- release_from_catalog() -----------------------------------------------------------------------------------

def from_catalog(conn, barcode, title, user, publisher='Pub'):
    return conn.execute('select release_from_catalog(%s, %s, %s, %s, %s)',
                        (barcode, title, publisher, Jsonb({'catalog': {'source': 'test'}}), user)).fetchone()[0]


@pytest.fixture
def ean(admin):
    """A fresh code in canonical EAN-13 form (a UPC-A with its leading 0); its release is removed afterwards."""
    code = '0' + random_upc()
    yield code
    admin.execute('delete from items where release_id in (select id from releases where barcode = %s)', (code,))
    admin.execute('delete from releases where barcode = %s', (code,))


def test_two_users_scanning_at_once_get_one_release(make_user, ean, admin):
    a, b = make_user('a'), make_user('b')
    out = {}
    with connect() as conn_a, connect() as conn_b:
        with as_role(conn_a, 'service_role'):
            out['a'] = from_catalog(conn_a, ean, 'From A', a)       # inserted, not yet committed

            def scan_b():
                with as_role(conn_b, 'service_role'):
                    out['b'] = from_catalog(conn_b, ean[1:], 'From B', b)   # the UPC-A spelling of the same code

            t = threading.Thread(target=scan_b)
            t.start()
            t.join(timeout=1)
            assert t.is_alive(), "B waits on A's uncommitted row"
        t.join(timeout=10)                                            # A committed; B's insert is a conflict
    assert out['a']['created'] is True and out['b']['created'] is False
    assert out['a']['id'] == out['b']['id'] and out['b']['title'] == 'From A'
    assert 'embedding' not in out['a']
    assert admin.execute('select count(*) from releases where barcode = %s', (ean,)).fetchone()[0] == 1


def test_a_later_catalog_answer_never_changes_the_release(make_user, ean, admin):
    a, b = make_user('a'), make_user('b')
    with connect() as conn, as_role(conn, 'service_role'):
        first = from_catalog(conn, ean, 'Right title', a)
    with connect() as conn, as_role(conn, 'service_role'):
        again = from_catalog(conn, ean, 'Ignore previous instructions', b, publisher='Spam')
    assert again['id'] == first['id'] and again['created'] is False
    row = admin.execute('select title, publisher, created_by from releases where barcode = %s', (ean,)).fetchone()
    assert row == ('Right title', 'Pub', a)


def test_catalog_text_is_trimmed_and_cut_to_length(make_user, ean):
    with connect() as conn, as_role(conn, 'service_role'):
        r = from_catalog(conn, ean, '  ' + 'x' * 1000, make_user('a'), publisher='p' * 500)
    assert r['title'] == 'x' * 300 and r['publisher'] == 'p' * 200


def test_user_b_cannot_alter_a_shared_release(make_user, ean, admin, category_id):
    a, b = make_user('a'), make_user('b')
    with connect() as conn, as_role(conn, 'service_role'):
        rel = from_catalog(conn, ean, 'Shared', a)
    attempts = [
        ("update releases set title = 'mine now' where id = %s", (rel['id'],)),
        ('delete from releases where id = %s', (rel['id'],)),
        ("insert into releases (barcode, title) values (%s, 'dupe') on conflict (barcode) do update set title = 'mine'", (ean,)),
        ("select release_from_catalog(%s, 'mine', null, '{}', null)", (ean,)),
        ("select begin_catalog_call('upcitemdb', null, 1000, 1000, 1000)", ()),
        ('select * from catalog_cache', ()),
        ('select * from catalog_calls', ()),
    ]
    with connect() as conn:
        for sql, args in attempts:
            with pytest.raises(errors.InsufficientPrivilege):
                with as_role(conn, 'authenticated', b):
                    conn.execute(sql, args)
        # B can read it and link their own item to it; that changes nothing about the release.
        with as_role(conn, 'authenticated', b):
            assert conn.execute('select title from releases where id = %s', (rel['id'],)).fetchone()[0] == 'Shared'
            conn.execute("insert into items (name, category_id, release_id) values ('my copy', %s, %s)",
                         (category_id, rel['id']))
    assert admin.execute('select title, created_by from releases where id = %s', (rel['id'],)).fetchone() == ('Shared', a)


# --- begin_catalog_call(): the shared budget --------------------------------------------------------------------

@pytest.fixture
def provider(admin):
    """A provider name of its own, so these counts never mix with real lookups; its rows are removed afterwards."""
    name = f'test-{uuid.uuid4().hex[:8]}'
    yield name
    admin.execute('delete from catalog_calls where provider = %s', (name,))


def begin(provider, user, daily=10, per_user=10, per_minute=10):
    with connect() as conn, as_role(conn, 'service_role'):
        return conn.execute('select begin_catalog_call(%s, %s, %s, %s, %s)',
                            (provider, user, daily, per_user, per_minute)).fetchone()[0]


def refused(provider, user, **caps) -> tuple[str, str]:
    with pytest.raises(psycopg.Error) as e:
        begin(provider, user, **caps)
    return e.value.sqlstate, e.value.diag.message_detail


def test_one_user_cannot_spend_the_shared_budget(make_user, provider):
    a, b = make_user('a'), make_user('b')
    begin(provider, a, per_user=2)
    begin(provider, a, per_user=2)
    assert refused(provider, a, per_user=2) == ('PT429', 'user')
    begin(provider, b, per_user=2)                       # B still has a share
    assert refused(provider, b, daily=3, per_user=2) == ('PT429', 'daily')


def test_per_minute_cap(make_user, provider):
    a = make_user('a')
    begin(provider, a, per_minute=1)
    assert refused(provider, a, per_minute=1) == ('PT503', 'minute')


def test_a_429_pauses_every_lookup_until_retry_after(make_user, admin, provider):
    a, b = make_user('a'), make_user('b')
    call = begin(provider, a)
    admin.execute("update catalog_calls set outcome = 'rate_limited', http_status = 429, "
                  "retry_after = now() + interval '30 seconds' where id = %s", (call,))
    assert refused(provider, b) == ('PT503', 'cooldown')
    admin.execute("update catalog_calls set retry_after = now() - interval '1 second' where id = %s", (call,))
    begin(provider, b)


def test_concurrent_calls_cannot_both_take_the_last_one(make_user, provider):
    users = [make_user(f'u{i}') for i in range(6)]
    results = []

    def go(u):
        try:
            results.append(begin(provider, u, daily=2))
        except psycopg.Error as e:
            results.append(e.sqlstate)

    threads = [threading.Thread(target=go, args=(u,)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(map(str, results)).count('PT429') == 4 and len(results) == 6


# --- a barcode on an intake job ("photograph the box" after a miss) ---------------------------------------------

def create(user, photo_ids, mode='single', barcode=None):
    with connect() as conn, as_role(conn, 'authenticated', user):
        return conn.execute('select id, barcode from create_intake_jobs(%s, %s, null, %s)',
                            (photo_ids, mode, barcode)).fetchall()


def test_intake_job_keeps_a_valid_barcode(admin, make_user):
    a = make_user('a')
    code = '0' + random_upc()
    [(_, stored)] = create(a, [photo(admin, a)], barcode=code)
    assert stored == code


@pytest.mark.parametrize('case', ['bad_digit', 'two_photos', 'group'])
def test_intake_barcode_rules(admin, make_user, case):
    a = make_user('a')
    code = '0' + random_upc()
    photos = [photo(admin, a)] + ([photo(admin, a)] if case == 'two_photos' else [])
    if case == 'bad_digit':
        code = code[:-1] + str((int(code[-1]) + 1) % 10)
    with pytest.raises(psycopg.Error) as e:
        create(a, photos, 'group' if case == 'group' else 'single', barcode=code)
    assert e.value.sqlstate == '22023'
    assert admin.execute('select count(*) from intake_jobs where owner_id = %s', (a,)).fetchone()[0] == 0
