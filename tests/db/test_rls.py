"""(1) User A cannot read or write user B's items; the shared/private boundary holds."""
import psycopg
import pytest
from psycopg import errors

from conftest import as_role, connect


@pytest.fixture
def two_users(make_user, category_id):
    """A owns an occasion and an item; B owns nothing yet."""
    a, b = make_user('a'), make_user('b')
    with connect() as conn, as_role(conn, 'authenticated', a):
        occasion = conn.execute(
            "insert into occasions (name, kind, occurred_on) values ('Christmas 2025', 'holiday', '2025-12-25') returning id"
        ).fetchone()[0]
        item = conn.execute(
            "insert into items (name, category_id, occasion_id, price_paid, location) "
            "values ('Ocarina of Time 3D', %s, %s, 39.99, 'hall closet') returning id",
            (category_id, occasion),
        ).fetchone()[0]
    return a, b, item, occasion


def test_owner_reads_own_item(two_users):
    a, _, item, _ = two_users
    with connect() as conn, as_role(conn, 'authenticated', a):
        assert conn.execute('select name from items where id = %s', (item,)).fetchone() == ('Ocarina of Time 3D',)


def test_other_user_cannot_read(two_users):
    _, b, item, occasion = two_users
    with connect() as conn, as_role(conn, 'authenticated', b):
        assert conn.execute('select count(*) from items').fetchone()[0] == 0
        assert conn.execute('select * from items where id = %s', (item,)).fetchall() == []
        assert conn.execute('select * from occasions where id = %s', (occasion,)).fetchall() == []


def test_other_user_cannot_update_or_delete(two_users, admin):
    _, b, item, _ = two_users
    with connect() as conn, as_role(conn, 'authenticated', b):
        assert conn.execute("update items set name = 'mine now' where id = %s", (item,)).rowcount == 0
        assert conn.execute('delete from items where id = %s', (item,)).rowcount == 0
    # Seen from outside RLS: untouched.
    assert admin.execute('select name, version from items where id = %s', (item,)).fetchone() == ('Ocarina of Time 3D', 1)


def test_other_user_cannot_insert_as_owner(two_users, category_id):
    a, b, _, _ = two_users
    with connect() as conn:
        with pytest.raises(errors.InsufficientPrivilege, match='row-level security'):
            with as_role(conn, 'authenticated', b):
                conn.execute("insert into items (owner_id, name, category_id) values (%s, 'planted', %s)", (a, category_id))


def test_other_user_cannot_move_item_to_themselves(two_users, admin):
    a, b, item, _ = two_users
    with connect() as conn, as_role(conn, 'authenticated', a):
        with pytest.raises(errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute('update items set owner_id = %s where id = %s', (b, item))
    assert admin.execute('select owner_id from items where id = %s', (item,)).fetchone()[0] == a


def test_cannot_link_to_another_users_occasion(two_users, category_id):
    """FK checks skip RLS, so the composite (owner_id, occasion_id) key is what stops this."""
    _, b, _, a_occasion = two_users
    with connect() as conn:
        with pytest.raises(errors.ForeignKeyViolation):
            with as_role(conn, 'authenticated', b):
                conn.execute("insert into items (name, category_id, occasion_id) values ('x', %s, %s)", (category_id, a_occasion))


def test_anon_gets_nothing(two_users):
    with connect() as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            with as_role(conn, 'anon'):
                conn.execute('select * from items')


def test_shared_tables_are_read_only_for_users(make_user):
    b = make_user('b')
    with connect() as conn:
        with as_role(conn, 'authenticated', b):
            conn.execute('select count(*) from releases').fetchone()
            assert conn.execute('select count(*) from categories where owner_id is null').fetchone()[0] > 0
        with pytest.raises(errors.InsufficientPrivilege):
            with as_role(conn, 'authenticated', b):
                conn.execute("insert into releases (title) values ('spam')")
        with as_role(conn, 'authenticated', b):  # built-in categories: visible, but the update matches no rows
            assert conn.execute("update categories set name = 'renamed' where owner_id is null").rowcount == 0
        with pytest.raises(errors.InsufficientPrivilege):
            with as_role(conn, 'authenticated', b):
                conn.execute("select claim_intake_job('sneaky')")


def test_share_link_hides_price_and_location(two_users):
    a, _, item, _ = two_users
    with connect() as conn:
        with as_role(conn, 'authenticated', a):
            token = conn.execute(
                "insert into collections (name, share_token) values ('Zelda shelf', new_share_token()) returning share_token"
            ).fetchone()[0]
            col = conn.execute('select id from collections where share_token = %s', (token,)).fetchone()[0]
            conn.execute('insert into collection_items (collection_id, item_id) values (%s, %s)', (col, item))
        with as_role(conn, 'anon'):
            cur = conn.execute('select * from get_shared_collection(%s)', (token,))
            columns = [d.name for d in cur.description]
            rows = cur.fetchall()
            assert conn.execute('select count(*) from get_shared_collection(%s)', ('wrong-token-' + 'x' * 20,)).fetchone()[0] == 0
    assert len(token) == 24
    assert [r[2] for r in rows] == ['Ocarina of Time 3D']
    assert not {'price_paid', 'location', 'notes', 'giver_id', 'occasion_id'} & set(columns)
