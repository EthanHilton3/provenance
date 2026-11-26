"""Shared fixtures for database tests against a local Supabase (`npx supabase start`).

Users are impersonated the way PostgREST does it: `set local role authenticated` plus the JWT claims in
`request.jwt.claims`, which is what auth.uid() reads. So these tests exercise the real RLS policies.
"""
import importlib.util
import json
import os
import random
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

# Local Supabase's documented default; override with PROVENANCE_DB_URL. Never point this at production.
DB_URL = os.environ.get('PROVENANCE_DB_URL', 'postgresql://postgres:postgres@127.0.0.1:54322/postgres')

REPO = Path(__file__).resolve().parents[2]
# The category tree's source file and generator (scripts/build_category_migration.py), for the tree tests.
_spec = importlib.util.spec_from_file_location('build_category_migration', REPO / 'scripts' / 'build_category_migration.py')
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)
load_tree, build_sql, MIGRATION = _builder.load_tree, _builder.build_sql, _builder.MIGRATION
SEED_MIGRATION = REPO / 'supabase' / 'migrations' / '20261117000100_seed_categories.sql'


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


def check_digit(body: str) -> str:
    """The GTIN mod-10 check digit for the digits before it (weights 3, 1, 3... from the right)."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def random_upc() -> str:
    """A random UPC-A in the 2xx restricted-circulation range (never a real product), with a valid check digit."""
    body = '2' + ''.join(random.choices('0123456789', k=10))
    return body + check_digit(body)
