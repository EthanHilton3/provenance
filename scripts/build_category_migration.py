"""Builds the category redesign migration from supabase/category_tree.json.

    python scripts/build_category_migration.py           # (re)write the migration
    python scripts/build_category_migration.py --check   # exit 1 if the migration is out of date

The tree file is what you review and edit; the SQL is generated and kept in the repo (the cloud runs the SQL).
After editing the tree, regenerate and commit both. tests/db checks the database against the tree file.
Standard library only.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT / 'supabase' / 'category_tree.json'
MIGRATION = ROOT / 'supabase' / 'migrations' / '20261125000000_category_redesign.sql'

TYPES = {'text', 'number', 'boolean', 'choice'}
FIELD_KEYS = ('key', 'label', 'type', 'options', 'scope', 'show_if')  # output order
OVERRIDABLE = {'key', 'options', 'show_if'}  # what a category may change on a library field


class TreeError(ValueError):
    pass


def check_field(f: dict, where: str, library: bool = False) -> None:
    """A library choice may leave its options to each category that uses it."""
    unknown = set(f) - set(FIELD_KEYS)
    if unknown:
        raise TreeError(f'{where}: unknown field keys {sorted(unknown)}')
    if not isinstance(f.get('key'), str) or not f['key'].isidentifier() or f['key'] != f['key'].lower():
        raise TreeError(f'{where}: key must be a lower_snake_case identifier')
    if not isinstance(f.get('label'), str) or not f['label'].strip():
        raise TreeError(f'{where}: missing label')
    if f.get('type') not in TYPES:
        raise TreeError(f'{where}: type must be one of {sorted(TYPES)}')
    if f['type'] == 'choice' and not (library and 'options' not in f):
        opts = f.get('options')
        if not opts or not all(isinstance(o, str) and o for o in opts) or len(set(opts)) != len(opts):
            raise TreeError(f'{where}: a choice needs distinct, non-empty string options')
    elif 'options' in f:
        raise TreeError(f'{where}: only a choice has options')
    if 'scope' in f and f['scope'] != 'product':
        raise TreeError(f'{where}: scope can only be "product"')
    if 'show_if' in f:
        s = f['show_if']
        if not isinstance(s, dict) or set(s) != {'key', 'equals'} or not isinstance(s['key'], str):
            raise TreeError(f'{where}: show_if is {{"key": ..., "equals": ...}}')


def ordered(f: dict) -> dict:
    return {k: f[k] for k in FIELD_KEYS if k in f}


def load_tree(path: Path = TREE) -> dict:
    """Reads and checks the tree; returns {'top': [category, ...]} with every template expanded."""
    raw = json.loads(path.read_text(encoding='utf-8'))
    library = raw['fields']
    for key, f in library.items():
        check_field({'key': key, **f}, f'fields.{key}', library=True)

    inline_seen: dict[str, str] = {}

    def expand(entries: list, where: str) -> list[dict]:
        out, keys = [], set()
        for e in entries:
            if isinstance(e, str):
                if e not in library:
                    raise TreeError(f'{where}: "{e}" is not in the field library')
                f = {'key': e, **library[e]}
            elif isinstance(e, dict) and e.get('key') in library:
                extra = set(e) - OVERRIDABLE
                if extra:
                    raise TreeError(f'{where}: library field "{e["key"]}" may only override options and show_if, '
                                    f'not {sorted(extra)}')
                f = {**library[e['key']], **e}
            elif isinstance(e, dict):
                f = dict(e)
                if f.get('key') in inline_seen:
                    raise TreeError(f'{where}: "{f.get("key")}" is also defined in {inline_seen[f["key"]]}; '
                                    'a field used twice belongs in the field library')
                inline_seen[f.get('key')] = where
            else:
                raise TreeError(f'{where}: a field is a library key or an object')
            check_field(f, f'{where}.{f["key"]}')
            if f['key'] in keys:
                raise TreeError(f'{where}: "{f["key"]}" is listed twice')
            keys.add(f['key'])
            out.append(ordered(f))
        return out

    def category(c: dict, where: str, inherited: dict) -> dict:
        unknown = set(c) - {'name', 'description', 'fields', 'children', 'renamed_from'}
        if unknown:
            raise TreeError(f'{where}: unknown keys {sorted(unknown)}')
        name = c.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or name != name.strip():
            raise TreeError(f'{where}: a name is 1 to 80 characters with no outer spaces')
        if not isinstance(c.get('description'), str) or not c['description'].strip():
            raise TreeError(f'{where}: every category needs a description')
        fields = expand(c.get('fields', []), f'{where} ({name})')
        visible = {**inherited, **{f['key']: f for f in fields}}
        for f in fields:
            if 'show_if' in f:
                target = visible.get(f['show_if']['key'])
                if target is None:
                    raise TreeError(f'{where}: {f["key"]}.show_if names "{f["show_if"]["key"]}", '
                                    'which is not in this or a parent template')
                if target['type'] == 'choice' and f['show_if']['equals'] not in target['options']:
                    raise TreeError(f'{where}: {f["key"]}.show_if value is not one of {target["key"]} options')
        return {'name': name, 'description': c['description'].strip(), 'fields': fields,
                'renamed_from': c.get('renamed_from'), 'children': c.get('children', []), '_visible': visible}

    top = []
    for i, c in enumerate(raw['categories']):
        t = category(c, f'categories[{i}]', {})
        kids = []
        for j, k in enumerate(t['children']):
            if k.get('children'):
                raise TreeError(f'{t["name"]} › {k.get("name")}: the built-in tree is two levels deep')
            kids.append(category(k, f'{t["name"]}.children[{j}]', t['_visible']))
        if len({k['name'] for k in kids}) != len(kids):
            raise TreeError(f'{t["name"]}: two children share a name')
        t['children'] = kids
        top.append(t)
    if len({t['name'] for t in top}) != len(top):
        raise TreeError('two top-level categories share a name')
    return {'top': top}


def q(s: str | None) -> str:
    return 'null' if s is None else "'" + s.replace("'", "''") + "'"


def j(v) -> str:
    return q(json.dumps(v, ensure_ascii=False, separators=(', ', ': '))) + '::jsonb'


HEADER = """\
-- Category redesign (docs/CATEGORY_REDESIGN.md, docs/CATEGORY_IMPLEMENTATION_PLAN.md).
--
-- GENERATED by scripts/build_category_migration.py from supabase/category_tree.json. Do not edit by hand:
-- edit the tree file and regenerate. The seed migration is not edited because the cloud project already ran it.
--
-- The CLI applies a migration file as one transaction, so if any step fails nothing is applied.
-- Safe to run twice (every step checks what is already there); tests/db relies on that to replay it.
--
-- Steps: 1 occasion kind "inherited"; 2 categories.description; 3 items.franchise/brand/signed_by, with any
-- attributes.brand/franchise moved into them; 4 rename the rows that survive, so their items keep the link;
-- 5 insert or update every built-in category (template and description); 6 re-point items in categories that
-- go away or split; 7 complete/complete_in_box -> completeness; 8 re-parent user categories under built-ins
-- that go away; 9 delete the obsolete built-ins (ON DELETE RESTRICT stops it if an item still points at one);
-- 10 check the result matches the tree file.
"""

STEPS_1_TO_3 = """\
-- 1. Occasion kind "inherited" (an heirloom is an item with a giver and this occasion).
alter table public.occasions drop constraint if exists occasions_kind_check;
alter table public.occasions add constraint occasions_kind_check
  check (kind in ('holiday', 'birthday', 'wedding', 'sale', 'trip', 'purchase', 'inherited', 'other'));

-- 2. What a category holds, written for people and the intake prompt: what it holds, examples, "not for" pointers.
alter table public.categories add column if not exists description text
  check (description is null or length(btrim(description)) between 1 and 1000);

-- 3. Franchise, brand and signed-by are on every item and searched across categories, so they are columns.
alter table public.items add column if not exists franchise text;
alter table public.items add column if not exists brand text;
alter table public.items add column if not exists signed_by text;
create index if not exists items_owner_franchise_idx on public.items (owner_id, franchise);
create index if not exists items_owner_brand_idx on public.items (owner_id, brand);

-- Move attributes.brand / attributes.franchise into the columns. A key is removed only once its value is in the
-- column (on a second run, a column that already holds a different value keeps it and the key stays as well).
update public.items i
set brand      = coalesce(i.brand, v.brand),
    franchise  = coalesce(i.franchise, v.franchise),
    attributes = i.attributes - array_remove(array[
                   case when v.brand is null or coalesce(i.brand, v.brand) = v.brand then 'brand' end,
                   case when v.franchise is null or coalesce(i.franchise, v.franchise) = v.franchise then 'franchise' end
                 ], null)
from (select id,
             nullif(btrim(attributes ->> 'brand'), '') as brand,
             nullif(btrim(attributes ->> 'franchise'), '') as franchise
      from public.items) v
where v.id = i.id and i.attributes ?| array['brand', 'franchise'];

-- Built-in category by path, for the steps below. Session-local; dropped at the end.
create or replace function pg_temp.builtin_category(p_parent text, p_name text) returns uuid
language sql stable as $$
  select c.id
  from public.categories c
  left join public.categories p on p.id = c.parent_id
  where c.owner_id is null and c.name = p_name
    and case when p_parent is null then c.parent_id is null
             else p.owner_id is null and p.parent_id is null and p.name = p_parent end
$$;
"""

STEP_6 = """\
-- 6. Re-point items (docs/CATEGORY_REDESIGN.md, "Where the old categories go"). Renamed rows kept their items in
-- step 4; these are the categories that split or go away. Anything still in an obsolete category stops step 9.
-- Movies & TV › Discs (was Physical media): tapes go to VHS & tapes.
update public.items set category_id = (select pg_temp.builtin_category('Movies & TV', 'VHS & tapes'))
where category_id = (select pg_temp.builtin_category('Movies & TV', 'Discs'))
  and lower(btrim(attributes ->> 'format')) = 'vhs';
-- Games & Puzzles (was Board Games & Puzzles): Board games by default; puzzles are moved by hand.
update public.items set category_id = (select pg_temp.builtin_category('Games & Puzzles', 'Board games'))
where category_id = (select pg_temp.builtin_category(null, 'Games & Puzzles'));
-- Toys (was Toys & Building Sets): Building sets when set_number is filled, else Toys (general).
update public.items set category_id = (select pg_temp.builtin_category('Toys', 'Building sets'))
where category_id = (select pg_temp.builtin_category(null, 'Toys'))
  and nullif(btrim(attributes ->> 'set_number'), '') is not null;
-- Tools › Hand & Power tools: Hand tools when power = Manual, else Power tools.
update public.items set category_id = (select pg_temp.builtin_category('Tools', 'Hand tools'))
where category_id = (select pg_temp.builtin_category('Tools', 'Hand & Power tools'))
  and lower(btrim(attributes ->> 'power')) = 'manual';
update public.items set category_id = (select pg_temp.builtin_category('Tools', 'Power tools'))
where category_id = (select pg_temp.builtin_category('Tools', 'Hand & Power tools'));
-- Children that fold into their parent: Books › Novels and › Other, Home Decor › Other, Electronics › Other,
-- Tools › Tool sets (a tool set is an item that contains tools).
update public.items set category_id = (select pg_temp.builtin_category(null, 'Books'))
where category_id in ((select pg_temp.builtin_category('Books', 'Novels')), (select pg_temp.builtin_category('Books', 'Other')));
update public.items set category_id = (select pg_temp.builtin_category(null, 'Home Decor'))
where category_id = (select pg_temp.builtin_category('Home Decor', 'Other'));
update public.items set category_id = (select pg_temp.builtin_category(null, 'Electronics'))
where category_id = (select pg_temp.builtin_category('Electronics', 'Other'));
update public.items set category_id = (select pg_temp.builtin_category(null, 'Tools'))
where category_id = (select pg_temp.builtin_category('Tools', 'Tool sets'));

-- 7. complete / complete_in_box (booleans) become completeness: true -> Complete in box, false -> Incomplete.
-- Only recognisable true/false values are converted; anything else stays as an "other detail".
update public.items
set attributes = (attributes - 'complete' - 'complete_in_box')
                 || jsonb_build_object('completeness',
                      case when coalesce(attributes -> 'complete_in_box', attributes -> 'complete')
                                in ('true'::jsonb, '"true"'::jsonb)
                           then 'Complete in box' else 'Incomplete' end)
where not attributes ? 'completeness'
  and coalesce(attributes -> 'complete_in_box', attributes -> 'complete')
      in ('true'::jsonb, 'false'::jsonb, '"true"'::jsonb, '"false"'::jsonb);
"""

STEPS_8_TO_10 = """\
-- 8. A user's category under a built-in that goes away moves up to that built-in's parent.
-- (A clash with one of the user's own names there stops the migration; the cloud had no user categories.)
with obsolete as (
  select c.id, c.parent_id
  from public.categories c
  left join public.categories p on p.id = c.parent_id
  where c.owner_id is null
    and not exists (select 1 from pg_temp.category_tree_new t where t.name = c.name and t.parent is not distinct from p.name)
)
update public.categories u set parent_id = o.parent_id
from obsolete o
where u.parent_id = o.id and u.owner_id is not null;

-- 9. Delete the built-ins that are not in the tree, children first.
delete from public.categories c
using public.categories p
where c.owner_id is null and p.id = c.parent_id
  and not exists (select 1 from pg_temp.category_tree_new t where t.parent = p.name and t.name = c.name);
delete from public.categories c
where c.owner_id is null and c.parent_id is null
  and not exists (select 1 from pg_temp.category_tree_new t where t.parent is null and t.name = c.name);

-- 10. The built-in tree is now exactly the tree file.
do $$
declare
  n_top int;
  n_child int;
begin
  select count(*) filter (where parent_id is null), count(*) filter (where parent_id is not null)
  into n_top, n_child
  from public.categories where owner_id is null;
  if n_top <> {n_top} or n_child <> {n_child} then
    raise exception 'category redesign: expected {n_top} top-level and {n_child} child built-ins, found % and %', n_top, n_child;
  end if;
  if exists (
    select 1 from pg_temp.category_tree_new t
    where not exists (
      select 1 from public.categories c left join public.categories p on p.id = c.parent_id
      where c.owner_id is null and c.name = t.name and p.name is not distinct from t.parent
        and c.description is not null)
  ) then
    raise exception 'category redesign: a category from the tree file is missing or has no description';
  end if;
end;
$$;

drop function pg_temp.builtin_category(text, text);
drop table pg_temp.category_tree_new;
"""


def build_sql(tree: dict) -> str:
    top = tree['top']
    parts = [HEADER, STEPS_1_TO_3]

    parts.append('-- 4. Rename in place where a row survives, so its items keep their link.')
    for t in top:
        if t['renamed_from']:
            parts.append(
                f"update public.categories set name = {q(t['name'])}\n"
                f"where owner_id is null and parent_id is null and name = {q(t['renamed_from'])}\n"
                f"  and (select pg_temp.builtin_category(null, {q(t['name'])})) is null;")
    for t in top:
        for c in t['children']:
            if c['renamed_from']:
                parts.append(
                    f"update public.categories set name = {q(c['name'])}\n"
                    f"where id = (select pg_temp.builtin_category({q(t['name'])}, {q(c['renamed_from'])}))\n"
                    f"  and (select pg_temp.builtin_category({q(t['name'])}, {q(c['name'])})) is null;")
    parts.append('')

    parts.append('-- 5. Every built-in category with its template and description: new rows inserted, existing ones updated.')
    parts.append('drop table if exists pg_temp.category_tree_new;')
    parts.append('create temp table category_tree_new (parent text, name text not null);')
    rows = [f'({q(None)}, {q(t["name"])})' for t in top]
    rows += [f'({q(t["name"])}, {q(c["name"])})' for t in top for c in t['children']]
    parts.append('insert into pg_temp.category_tree_new (parent, name) values\n  ' + ',\n  '.join(rows) + ';')
    parts.append('')

    on_conflict = ('on conflict on constraint categories_owner_id_parent_id_name_key\n'
                   'do update set description = excluded.description, field_template = excluded.field_template;')
    values = ',\n'.join(f'  ({q(t["name"])},\n   {q(t["description"])},\n   {j(t["fields"])})' for t in top)
    parts.append('insert into public.categories (owner_id, parent_id, name, description, field_template)\n'
                 'select null, null, v.name, v.description, v.field_template\n'
                 f'from (values\n{values}\n) as v (name, description, field_template)\n{on_conflict}')
    parts.append('')
    for t in top:
        if not t['children']:
            continue
        values = ',\n'.join(f'  ({q(c["name"])},\n   {q(c["description"])},\n   {j(c["fields"])})'
                            for c in t['children'])
        parts.append(f'-- {t["name"]}\n'
                     'insert into public.categories (owner_id, parent_id, name, description, field_template)\n'
                     f'select null, (select pg_temp.builtin_category(null, {q(t["name"])})), v.name, v.description, '
                     'v.field_template\n'
                     f'from (values\n{values}\n) as v (name, description, field_template)\n{on_conflict}')
        parts.append('')

    parts.append(STEP_6)
    n_top = len(top)
    n_child = sum(len(t['children']) for t in top)
    parts.append(STEPS_8_TO_10.replace('{n_top}', str(n_top)).replace('{n_child}', str(n_child)))
    return '\n'.join(parts)


def main(argv: list[str]) -> int:
    try:
        sql = build_sql(load_tree())
    except TreeError as e:
        print(f'category_tree.json: {e}', file=sys.stderr)
        return 2
    if '--check' in argv:
        current = MIGRATION.read_text(encoding='utf-8') if MIGRATION.exists() else ''
        if current != sql:
            print(f'{MIGRATION.relative_to(ROOT)} is out of date; run scripts/build_category_migration.py', file=sys.stderr)
            return 1
        print('migration is up to date')
        return 0
    MIGRATION.write_bytes(sql.encode('utf-8'))
    print(f'wrote {MIGRATION.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
