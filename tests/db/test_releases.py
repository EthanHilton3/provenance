"""(3) Two people scanning the same new barcode at once end up with one shared release (ON CONFLICT)."""
import threading

import pytest
from psycopg import errors

from conftest import as_role, connect, random_upc

FIND_OR_CREATE = """
insert into releases (barcode, title, created_by) values (%(barcode)s, %(title)s, %(user)s)
on conflict (barcode) do nothing
returning id
"""


def find_or_create(conn, barcode: str, title: str, user) -> tuple:
    """Returns (release_id, created). The follow-up select is a separate statement on purpose: under READ
    COMMITTED it gets a fresh snapshot that sees the other transaction's committed row."""
    row = conn.execute(FIND_OR_CREATE, {'barcode': barcode, 'title': title, 'user': user}).fetchone()
    if row:
        return row[0], True
    return conn.execute('select id from releases where barcode = %s', (barcode,)).fetchone()[0], False


@pytest.fixture
def upc(admin):
    """A random UPC-A in the 2xx restricted-circulation range (never a real product); cleaned up after."""
    code = random_upc()
    yield code
    admin.execute("delete from releases where barcode = '0' || %s", (code,))


def test_concurrent_scans_create_one_release(make_user, upc, admin):
    a, b = make_user('a'), make_user('b')
    results = {}

    with connect() as conn_a, connect() as conn_b:
        with as_role(conn_a, 'service_role'):
            # A's insert is in, not committed. B's scan uses the EAN-13 spelling of the same barcode.
            results['a'] = find_or_create(conn_a, upc, 'Release from A', a)

            def scan_b():
                with as_role(conn_b, 'service_role'):
                    results['b'] = find_or_create(conn_b, '0' + upc, 'Release from B', b)

            t = threading.Thread(target=scan_b)
            t.start()
            t.join(timeout=1)
            assert t.is_alive(), "B waits on A's uncommitted row for the same barcode"
        # A commits on leaving the block; B's insert then resolves as a conflict.
        t.join(timeout=10)

    (a_id, a_created), (b_id, b_created) = results['a'], results['b']
    assert a_created and not b_created
    assert a_id == b_id
    rows = admin.execute("select barcode, title from releases where barcode = '0' || %s", (upc,)).fetchall()
    assert rows == [('0' + upc, 'Release from A')]


def test_plain_insert_of_duplicate_barcode_fails(upc):
    with connect() as conn:
        with as_role(conn, 'service_role'):
            conn.execute("insert into releases (barcode, title) values (%s, 'first')", (upc,))
        with pytest.raises(errors.UniqueViolation):
            with as_role(conn, 'service_role'):
                conn.execute("insert into releases (barcode, title) values (%s, 'second')", ('0' + upc,))


def test_barcode_is_normalized(upc, admin):
    with connect() as conn, as_role(conn, 'service_role'):
        stored = conn.execute(
            "insert into releases (barcode, title) values (%s, 'x') returning barcode", (f'{upc[:6]}-{upc[6:]}',)
        ).fetchone()[0]
    assert stored == '0' + upc
