"""The category redesign migration, replayed on the old tree with items in it.

`db reset` has already applied the migration, so each test rebuilds the old tree inside one transaction (renamed rows
get their old names back, then the seed migration re-creates the rows the redesign deleted), adds items the way the
old forms stored them, runs the redesign migration again and checks where everything landed. The transaction is
rolled back, so the database is left as it was. This also proves the migration is safe to run twice.
"""
import json
import uuid

import psycopg
import pytest

from conftest import MIGRATION, SEED_MIGRATION, connect, load_tree

PATH_OF = """
    select coalesce(p.name || ' › ', '') || c.name
    from categories c left join categories p on p.id = c.parent_id where c.id = %s
"""


def builtin(conn, parent, name):
    row = conn.execute(
        "select c.id from categories c left join categories p on p.id = c.parent_id "
        "where c.owner_id is null and c.name = %s and p.name is not distinct from %s", (name, parent)).fetchone()
    assert row, f'no built-in {parent} › {name}'
    return row[0]


def restore_old_tree(conn):
    for t in load_tree()['top']:
        if t['renamed_from']:
            conn.execute("update categories set name = %s where owner_id is null and parent_id is null and name = %s",
                         (t['renamed_from'], t['name']))
    for t in load_tree()['top']:
        for c in t['children']:
            if c['renamed_from']:
                conn.execute('update categories set name = %s where id = %s',
                             (c['renamed_from'], builtin(conn, t['renamed_from'] or t['name'], c['name'])))
    conn.execute(SEED_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture
def old_world(make_user):
    """A connection inside a transaction that is always rolled back, with the old tree restored."""
    owner = make_user('redesign')
    with connect() as conn:
        with conn.transaction(force_rollback=True):
            restore_old_tree(conn)
            yield conn, owner


def add_item(conn, owner, parent, name, attributes=None, **columns):
    cols = {'owner_id': owner, 'name': 'thing', 'category_id': builtin(conn, parent, name),
            'attributes': json.dumps(attributes or {}), **columns}
    sql = f"insert into items ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) returning id"
    return conn.execute(sql, list(cols.values())).fetchone()[0]


def run_migration(conn):
    conn.execute(MIGRATION.read_text(encoding='utf-8'))


def item(conn, item_id):
    cat, attrs, brand, franchise = conn.execute(
        'select category_id, attributes, brand, franchise from items where id = %s', (item_id,)).fetchone()
    return conn.execute(PATH_OF, (cat,)).fetchone()[0], attrs, brand, franchise


def test_old_tree_is_really_restored(old_world):
    conn, _ = old_world
    names = {r[0] for r in conn.execute('select name from categories where owner_id is null').fetchall()}
    assert {'Board Games & Puzzles', 'Physical media', 'Novels', 'Hand & Power tools', 'Tool sets'} <= names


# (old parent, old name, attributes) -> new path. One item in every old category, more where the rule splits.
CASES = [
    (('Movies & TV', 'Physical media', {'format': 'VHS'}), 'Movies & TV › VHS & tapes'),
    (('Movies & TV', 'Physical media', {'format': 'Blu-ray'}), 'Movies & TV › Discs'),
    ((None, 'Board Games & Puzzles', {}), 'Games & Puzzles › Board games'),
    ((None, 'Toys & Building Sets', {'set_number': '75192'}), 'Toys › Building sets'),
    ((None, 'Toys & Building Sets', {'set_number': ' '}), 'Toys'),
    ((None, 'Toys & Building Sets', {}), 'Toys'),
    (('Tools', 'Hand & Power tools', {'power': 'Manual'}), 'Tools › Hand tools'),
    (('Tools', 'Hand & Power tools', {'power': 'Cordless'}), 'Tools › Power tools'),
    (('Tools', 'Hand & Power tools', {}), 'Tools › Power tools'),
    (('Tools', 'Tool sets', {}), 'Tools'),
    (('Books', 'Novels', {}), 'Books'),
    (('Books', 'Other', {}), 'Books'),
    (('Books', 'Manga & Comics', {}), 'Books › Manga'),
    (('Home Decor', 'Other', {}), 'Home Decor'),
    (('Home Decor', 'Wall art & Frames', {}), 'Home Decor › Wall art & Posters'),
    (('Home Decor', 'Seasonal', {}), 'Home Decor › Seasonal'),
    (('Home Decor', 'Candles & Fragrance', {}), 'Home Decor › Candles & Fragrance'),
    (('Electronics', 'Other', {}), 'Electronics'),
    ((None, 'Electronics', {}), 'Electronics'),
    (('Music', 'Albums & Vinyl', {}), 'Music › Albums'),
    (('Music', 'Instruments', {}), 'Music › Instruments'),
    (('Kitchen', 'Drinkware & Dishes', {}), 'Kitchen › Drinkware'),
    (('Kitchen', 'Appliances', {}), 'Kitchen › Appliances'),
    ((None, 'Collectibles & Memorabilia', {}), 'Memorabilia & Keepsakes'),
    ((None, 'Clothing & Textiles', {}), 'Clothing & Linens'),
    ((None, 'Bags & Cases', {}), 'Bags & Cases'),
    ((None, 'Other', {}), 'Other'),
    (('Video Games', 'Games', {}), 'Video Games › Games'),
    (('Video Games', 'Consoles', {}), 'Video Games › Consoles'),
    (('Video Games', 'Controllers', {}), 'Video Games › Controllers'),
    (('Video Games', 'Accessories', {}), 'Video Games › Accessories'),
    ((None, 'Video Games', {}), 'Video Games'),
    ((None, 'Movies & TV', {}), 'Movies & TV'),
    ((None, 'Books', {}), 'Books'),
    ((None, 'Music', {}), 'Music'),
    ((None, 'Home Decor', {}), 'Home Decor'),
    ((None, 'Kitchen', {}), 'Kitchen'),
    ((None, 'Tools', {}), 'Tools'),
]


def test_every_old_category_lands_in_the_right_new_one(old_world):
    conn, owner = old_world
    assert len({(p, n) for (p, n, _), _ in CASES}) == 33  # every one of the 14 + 19 old built-ins has a case
    physical_media = builtin(conn, 'Movies & TV', 'Physical media')
    ids = [(add_item(conn, owner, p, n, attrs), expected) for (p, n, attrs), expected in CASES]
    run_migration(conn)
    assert [item(conn, i)[0] for i, _ in ids] == [expected for _, expected in ids]
    # A renamed row keeps its id, so its items never had to move.
    assert builtin(conn, 'Movies & TV', 'Discs') == physical_media


def test_brand_and_franchise_move_to_columns(old_world):
    conn, owner = old_world
    lego = add_item(conn, owner, None, 'Toys & Building Sets', {'brand': ' LEGO ', 'set_number': '10294'})
    zelda = add_item(conn, owner, None, 'Collectibles & Memorabilia', {'franchise': 'Zelda', 'numbered': '3/100'})
    blank = add_item(conn, owner, None, 'Kitchen', {'brand': ''})
    kept = add_item(conn, owner, None, 'Kitchen', {'brand': 'Pyrex'}, brand='Anchor Hocking')  # column already set
    run_migration(conn)
    assert item(conn, lego) == ('Toys › Building sets', {'set_number': '10294'}, 'LEGO', None)
    assert item(conn, zelda) == ('Memorabilia & Keepsakes', {'numbered': '3/100'}, None, 'Zelda')
    assert item(conn, blank)[1:] == ({}, None, None)
    # A column that already holds a different value keeps it, and the attribute is not thrown away.
    assert item(conn, kept)[1:] == ({'brand': 'Pyrex'}, 'Anchor Hocking', None)


def test_complete_flags_become_completeness(old_world):
    conn, owner = old_world
    cib = add_item(conn, owner, 'Video Games', 'Games', {'complete_in_box': True, 'platform': 'Switch'})
    loose = add_item(conn, owner, 'Video Games', 'Games', {'complete_in_box': False})
    board = add_item(conn, owner, None, 'Board Games & Puzzles', {'complete': True, 'player_count': '2-4'})
    both = add_item(conn, owner, None, 'Board Games & Puzzles', {'complete': True, 'complete_in_box': False})
    already = add_item(conn, owner, 'Video Games', 'Games', {'complete_in_box': True, 'completeness': 'Loose item'})
    odd = add_item(conn, owner, 'Video Games', 'Games', {'complete_in_box': 'mostly'})
    run_migration(conn)
    assert item(conn, cib)[1] == {'completeness': 'Complete in box', 'platform': 'Switch'}
    assert item(conn, loose)[1] == {'completeness': 'Incomplete'}
    assert item(conn, board)[:2] == ('Games & Puzzles › Board games', {'completeness': 'Complete in box', 'player_count': '2-4'})
    assert item(conn, both)[1] == {'completeness': 'Incomplete'}  # complete_in_box wins over complete
    assert item(conn, already)[1] == {'complete_in_box': True, 'completeness': 'Loose item'}  # nothing overwritten
    assert item(conn, odd)[1] == {'complete_in_box': 'mostly'}  # not a yes/no: kept as an other detail


def test_user_category_under_a_deleted_built_in_moves_up(old_world):
    conn, owner = old_world
    novels = builtin(conn, 'Books', 'Novels')
    mine = conn.execute("insert into categories (owner_id, parent_id, name) values (%s, %s, 'Signed first editions') "
                        "returning id", (owner, novels)).fetchone()[0]
    thing = conn.execute("insert into items (owner_id, name, category_id) values (%s, 'Dune', %s) returning id",
                         (owner, mine)).fetchone()[0]
    run_migration(conn)
    assert conn.execute(PATH_OF, (mine,)).fetchone()[0] == 'Books › Signed first editions'
    assert conn.execute('select category_id from items where id = %s', (thing,)).fetchone()[0] == mine
    assert conn.execute('select count(*) from categories where id = %s', (novels,)).fetchone()[0] == 0


def test_an_item_left_in_an_obsolete_category_stops_the_migration(old_world):
    """The RESTRICT foreign key is the safety net: a category that still has items cannot be deleted."""
    conn, owner = old_world
    # A built-in that no rule handles (as if the cloud had a category this migration does not know).
    extra = conn.execute("insert into categories (owner_id, parent_id, name) values (null, null, 'Mystery') "
                         "returning id").fetchone()[0]
    conn.execute("insert into items (owner_id, name, category_id) values (%s, 'x', %s)", (owner, extra))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            run_migration(conn)


def test_migration_twice_changes_nothing(old_world):
    conn, owner = old_world
    a = add_item(conn, owner, None, 'Toys & Building Sets', {'brand': 'LEGO', 'set_number': '1'})
    run_migration(conn)
    first = conn.execute('select id, category_id, attributes, brand, version from items where id = %s', (a,)).fetchone()
    tree = conn.execute('select id, parent_id, name, description, field_template from categories order by id').fetchall()
    run_migration(conn)
    assert conn.execute('select id, category_id, attributes, brand, version from items where id = %s', (a,)).fetchone() == first
    assert conn.execute('select id, parent_id, name, description, field_template from categories order by id').fetchall() == tree


def test_new_columns_are_the_users_own(make_user, category_id):
    """franchise, brand and signed_by behave like the other item columns under RLS."""
    from conftest import as_role
    a, b = make_user('a'), make_user('b')
    with connect() as conn:
        with as_role(conn, 'authenticated', a):
            row = conn.execute(
                "insert into items (name, category_id, franchise, brand, signed_by) "
                "values ('Signed Zelda poster', %s, 'Zelda', 'Nintendo', 'Eiji Aonuma') returning id", (category_id,)
            ).fetchone()[0]
            assert conn.execute("select count(*) from items where franchise = 'Zelda' and brand = 'Nintendo'").fetchone() == (1,)
        with as_role(conn, 'authenticated', b):
            assert conn.execute('select count(*) from items where id = %s', (row,)).fetchone() == (0,)
    assert uuid.UUID(str(row))
