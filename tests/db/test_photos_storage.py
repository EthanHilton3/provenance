"""The private `photos` bucket and the photos table: each user reaches only their own `<user id>/` prefix."""
import uuid

import psycopg
import pytest
from psycopg import errors

from conftest import as_role, connect


def path_for(owner: uuid.UUID) -> str:
    return f'{owner}/{uuid.uuid4()}.jpg'


def put(conn, name: str):
    conn.execute("insert into storage.objects (bucket_id, name) values ('photos', %s)", (name,))


@pytest.fixture
def two_users(make_user, admin):
    a, b = make_user('a'), make_user('b')
    yield a, b
    # Storage refuses plain deletes unless told this is deliberate (the Storage API is the normal way).
    with connect() as conn:
        conn.execute("set local storage.allow_delete_query = 'true'")
        conn.execute("delete from storage.objects where bucket_id = 'photos' and (storage.foldername(name))[1] = any(%s)",
                     ([str(a), str(b)],))


def test_bucket_is_private_jpeg_only_and_size_limited(admin):
    row = admin.execute("select public, allowed_mime_types, file_size_limit from storage.buckets where id = 'photos'").fetchone()
    assert row == (False, ['image/jpeg'], 5 * 1024 * 1024)


def test_owner_can_write_read_and_delete_own_prefix(two_users):
    a, _ = two_users
    name = path_for(a)
    with connect() as conn, as_role(conn, 'authenticated', a):
        put(conn, name)
        assert conn.execute('select count(*) from storage.objects where name = %s', (name,)).fetchone()[0] == 1
        conn.execute("set local storage.allow_delete_query = 'true'")
        assert conn.execute('delete from storage.objects where name = %s', (name,)).rowcount == 1


def test_cannot_write_into_another_users_prefix_or_the_bucket_root(two_users):
    a, b = two_users
    for name in (path_for(a), 'loose.jpg'):
        with connect() as conn:
            with pytest.raises(errors.InsufficientPrivilege, match='row-level security'):
                with as_role(conn, 'authenticated', b):
                    put(conn, name)


def test_other_user_cannot_read_or_delete(two_users, admin):
    a, b = two_users
    name = path_for(a)
    with connect() as conn, as_role(conn, 'authenticated', a):
        put(conn, name)
    with connect() as conn, as_role(conn, 'authenticated', b):
        assert conn.execute("select count(*) from storage.objects where bucket_id = 'photos'").fetchone()[0] == 0
        conn.execute("set local storage.allow_delete_query = 'true'")
        assert conn.execute('delete from storage.objects where name = %s', (name,)).rowcount == 0
    assert admin.execute('select count(*) from storage.objects where name = %s', (name,)).fetchone()[0] == 1


def test_no_update_policy_so_files_cannot_be_overwritten(two_users):
    a, _ = two_users
    name = path_for(a)
    with connect() as conn, as_role(conn, 'authenticated', a):
        put(conn, name)
        assert conn.execute("update storage.objects set name = %s where name = %s", (path_for(a), name)).rowcount == 0


def test_anon_gets_nothing(two_users):
    a, _ = two_users
    with connect() as conn, as_role(conn, 'authenticated', a):
        put(conn, path_for(a))
    with connect() as conn, as_role(conn, 'anon'):
        assert conn.execute("select count(*) from storage.objects where bucket_id = 'photos'").fetchone()[0] == 0
    with connect() as conn:
        with pytest.raises(errors.InsufficientPrivilege, match='row-level security'):
            with as_role(conn, 'anon'):
                put(conn, path_for(a))


# --- the photos table, which the storage path has to agree with ---------------------------------------------

def add_photo(conn, owner, path=None, **extra):
    cols = {'storage_path': path or path_for(owner), **extra}
    return conn.execute(
        f"insert into photos ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) returning id, position",
        list(cols.values()),
    ).fetchone()


def test_unattached_photo_is_allowed_and_defaults_to_position_0(two_users):
    a, _ = two_users
    with connect() as conn, as_role(conn, 'authenticated', a):
        assert add_photo(conn, a)[1] == 0


def test_photo_path_must_start_with_the_owners_id(two_users):
    a, b = two_users
    with connect() as conn:
        with pytest.raises(errors.CheckViolation):
            with as_role(conn, 'authenticated', b):
                add_photo(conn, b, path=path_for(a))


def test_cannot_attach_a_photo_to_another_users_item(two_users, category_id):
    a, b = two_users
    with connect() as conn, as_role(conn, 'authenticated', a):
        item = conn.execute("insert into items (name, category_id) values ('x', %s) returning id", (category_id,)).fetchone()[0]
    with connect() as conn:
        with pytest.raises(errors.ForeignKeyViolation):  # the composite (owner_id, item_id) key
            with as_role(conn, 'authenticated', b):
                add_photo(conn, b, item_id=item)


def test_other_user_cannot_see_or_delete_a_photo_row(two_users, admin):
    a, b = two_users
    with connect() as conn, as_role(conn, 'authenticated', a):
        photo = add_photo(conn, a)[0]
    with connect() as conn, as_role(conn, 'authenticated', b):
        assert conn.execute('select count(*) from photos').fetchone()[0] == 0
        assert conn.execute('delete from photos where id = %s', (photo,)).rowcount == 0
    assert admin.execute('select count(*) from photos where id = %s', (photo,)).fetchone()[0] == 1
