"""Beyond the three required tests: optimistic locking and the built-in category tree."""
from conftest import MIGRATION, as_role, build_sql, connect, load_tree


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


def test_category_tree_matches_tree_file(admin):
    """The built-in tree in the database is exactly supabase/category_tree.json: names, descriptions, templates."""
    expected = {}
    for t in load_tree()['top']:
        expected[(None, t['name'])] = (t['description'], t['fields'])
        for c in t['children']:
            expected[(t['name'], c['name'])] = (c['description'], c['fields'])
    actual = {(r[0], r[1]): (r[2], r[3]) for r in admin.execute("""
        select p.name, c.name, c.description, c.field_template
        from categories c left join categories p on p.id = c.parent_id
        where c.owner_id is null
    """).fetchall()}
    assert actual == expected


def test_migration_is_generated_from_tree_file():
    """The committed SQL is what the generator makes from the tree file (nobody edited one without the other)."""
    assert MIGRATION.read_text(encoding='utf-8') == build_sql(load_tree())


def test_children_inherit_fields(admin, category_id):
    keys = [f['key'] for f in admin.execute('select category_fields(%s)', (category_id,)).fetchone()[0]]
    assert keys == ['region', 'platform', 'edition', 'completeness']  # Video Games, then Games


def test_tree_shape_and_descriptions(admin):
    """19 top-level built-ins and 79 children, every one reachable from a top-level one and described."""
    rows = admin.execute("""
        with recursive tree as (
          select id, 0 as depth from categories where parent_id is null and owner_id is null
          union all
          select c.id, tree.depth + 1 from categories c join tree on c.parent_id = tree.id where c.owner_id is null
        )
        select depth, count(*) from tree group by depth order by depth
    """).fetchall()
    assert rows == [(0, 19), (1, 79)]
    total, described = admin.execute(
        "select count(*), count(*) filter (where length(btrim(description)) > 20) from categories where owner_id is null"
    ).fetchone()
    assert total == described == 98


def test_same_key_means_same_label_and_type(admin):
    seen = {}
    for name, template in admin.execute('select name, field_template from categories where owner_id is null').fetchall():
        for f in template:
            label_type = (f['label'], f['type'])
            assert seen.setdefault(f['key'], (label_type, name))[0] == label_type, (
                f'{f["key"]} is {label_type} in {name} but {seen[f["key"]][0]} in {seen[f["key"]][1]}')


def test_show_if_names_a_field_of_the_same_or_a_parent_template(admin):
    checked = 0
    for (cid, name) in admin.execute('select id, name from categories where owner_id is null').fetchall():
        fields = {f['key']: f for f in admin.execute('select category_fields(%s)', (cid,)).fetchone()[0]}
        for f in fields.values():
            if 'show_if' in f:
                target = fields.get(f['show_if']['key'])
                assert target is not None, f'{name}: {f["key"]} depends on a field it does not have'
                if target['type'] == 'choice':
                    assert f['show_if']['equals'] in target['options']
                checked += 1
    assert checked == 5  # Albums: four vinyl-only fields; Board games: expansion_for


def test_field_template_tags():
    """scope and show_if are the only additions to a field, and scope is only ever "product"."""
    for t in load_tree()['top']:
        for c in [t, *t['children']]:
            for f in c['fields']:
                assert set(f) <= {'key', 'label', 'type', 'options', 'scope', 'show_if'}
                assert f.get('scope', 'product') == 'product'


def test_inherited_occasion_kind_is_accepted(make_user):
    a = make_user('a')
    with connect() as conn, as_role(conn, 'authenticated', a):
        kind = conn.execute(
            "insert into occasions (name, kind) values ('From Grandma', 'inherited') returning kind").fetchone()[0]
        assert kind == 'inherited'
