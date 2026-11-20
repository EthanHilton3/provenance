"""Beyond the three required tests: optimistic locking and the seeded category tree."""
import re
from pathlib import Path

import pytest

from conftest import as_role, connect

INTAKE_PY = Path(__file__).parents[3] / 'CS-452 Database' / '26-11-16 collection intake feasibility' / 'intake.py'


def test_stale_version_update_is_rejected(make_user, category_id):
    a = make_user('a')
    with connect() as conn:
        with as_role(conn, 'authenticated', a):
            item = conn.execute(
                "insert into items (name, category_id) values ('GameCube controller', %s) returning id", (category_id,)
            ).fetchone()[0]
        # Phone and laptop both read version 1. The phone saves first.
        with as_role(conn, 'authenticated', a):
            phone = conn.execute("update items set location = 'shelf' where id = %s and version = 1 returning version", (item,))
            assert phone.fetchone() == (2,)
        with as_role(conn, 'authenticated', a):
            laptop = conn.execute("update items set location = 'drawer' where id = %s and version = 1", (item,))
            assert laptop.rowcount == 0  # stale: the API returns 409 and reloads
        with as_role(conn, 'authenticated', a):  # clients can't fake the version
            assert conn.execute('update items set version = 100 where id = %s returning version', (item,)).fetchone() == (3,)
            assert conn.execute('select location from items where id = %s', (item,)).fetchone() == ('shelf',)


def test_category_tree_matches_feasibility_list(admin):
    """Every leaf path from intake.py's CATEGORIES exists as a built-in category."""
    if not INTAKE_PY.exists():
        pytest.skip('needs the CS-452 Database repo next to this one')
    source = INTAKE_PY.read_text(encoding='utf-8')
    block = re.search(r'CATEGORIES = \((.*?)\n\)', source, re.S).group(1)
    expected = set(re.findall(r"'([^']+)'", block))
    leaves = {r[0] for r in admin.execute("""
        with recursive tree as (
          select id, name::text as path from categories where parent_id is null and owner_id is null
          union all
          select c.id, tree.path || ' > ' || c.name from categories c join tree on c.parent_id = tree.id
        )
        select path from tree t where not exists (select 1 from categories c where c.parent_id = t.id)
    """).fetchall()}
    assert len(expected) == 25
    assert leaves == expected


def test_children_inherit_fields(admin, category_id):
    keys = [f['key'] for f in admin.execute('select category_fields(%s)', (category_id,)).fetchone()[0]]
    assert keys == ['platform', 'region', 'edition', 'complete_in_box']  # Video Games, then Games
