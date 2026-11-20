"""Shared fixtures for database tests against a local Supabase (`npx supabase start`).

Users are impersonated the way PostgREST does it: `set local role authenticated` plus the JWT claims in
`request.jwt.claims`, which is what auth.uid() reads. So these tests exercise the real RLS policies.
"""
import json
import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest

# Local Supabase's documented default; override with PROVENANCE_DB_URL. Never point this at production.
DB_URL = os.environ.get('PROVENANCE_DB_URL', 'postgresql://postgres:postgres@127.0.0.1:54322/postgres')


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(DB_URL, autocommit=autocommit)


@contextmanager
def as_role(conn: psycopg.Connection, role: str, user_id: uuid.UUID | None = None):
    """One transaction as `role` (authenticated / anon / service_role), committed on success."""
    claims = {'role': role, **({'sub': str(user_id)} if user_id else {})}
    with conn.transaction():
        conn.execute(f'set local role {role}')
        conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
        yield conn


@pytest.fixture
def admin():
    with connect(autocommit=True) as conn:
        yield conn


@pytest.fixture
def make_user(admin):
    """Creates auth.users rows; deleting them at teardown cascades to everything they own."""
    created = []

    def _make(label: str) -> uuid.UUID:
        uid = uuid.uuid4()
        admin.execute(
            "insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
            (uid, f'{label}-{uid.hex[:8]}@test.local'),
        )
        created.append(uid)
        return uid

    yield _make
    if created:
        admin.execute('delete from auth.users where id = any(%s)', (created,))


@pytest.fixture
def category_id(admin) -> uuid.UUID:
    return admin.execute(
        "select c.id from categories c join categories p on p.id = c.parent_id "
        "where p.name = 'Video Games' and c.name = 'Games' and c.owner_id is null"
    ).fetchone()[0]
