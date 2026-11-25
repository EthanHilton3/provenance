import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { buildEntries, holds, normalize, searchCategories } from './categorySearch.js'

// The real built-in tree, shaped like GET /api/categories rows.
const tree = JSON.parse(readFileSync(new URL('../../../supabase/category_tree.json', import.meta.url), 'utf8'))
const rows = []
for (const t of tree.categories) {
  rows.push({ id: t.name, parent_id: null, name: t.name, owner_id: null, description: t.description })
  for (const c of t.children) rows.push({ id: `${t.name}/${c.name}`, parent_id: t.name, name: c.name, owner_id: null, description: c.description })
}
const entries = buildEntries(rows)
const top = (q, n = 1) => searchCategories(entries, q, n).map((e) => e.path)
const all = (q) => searchCategories(entries, q).map((e) => e.path)

test('normalize folds case, accents, & and punctuation', () => {
  assert.equal(normalize('  Pokémon: Red & Blue! '), 'pokemon red and blue')
  assert.equal(normalize(null), '')
})

test('holds stops at the first "not for" sentence or clause', () => {
  assert.equal(holds('Mugs and cups. Not popcorn buckets (Popcorn & snack ware).'), 'Mugs and cups.')
  assert.equal(holds('Decorations for a holiday. Decorations only: not holiday mugs (Kitchen).'), 'Decorations for a holiday. Decorations only:')
  assert.equal(holds('Notebooks and notepads.'), 'Notebooks and notepads.') // "Not" only as a word
  assert.equal(holds(undefined), '')
})

test('every category is an entry, parents before children, Other last', () => {
  assert.equal(entries.length, 98)
  assert.equal(entries[0].path, 'Bags & Cases')
  assert.equal(entries.at(-1).path, 'Other')
  const kitchen = entries.findIndex((e) => e.path === 'Kitchen')
  assert.equal(entries[kitchen + 1].path, 'Kitchen › Appliances')
  assert.equal(entries[kitchen].general, true)
  assert.equal(entries.find((e) => e.path === 'Bags & Cases').general, false)
})

test('an empty query lists everything in tree order', () => {
  assert.deepEqual(searchCategories(entries, '  ').map((e) => e.id), entries.map((e) => e.id))
  assert.equal(searchCategories(entries, '', 5).length, 5)
})

test('names win: typing a category name finds it first', () => {
  assert.deepEqual(top('drinkware'), ['Kitchen › Drinkware'])
  assert.deepEqual(top('books'), ['Books'])
  assert.deepEqual(top('board'), ['Games & Puzzles › Board games'])
  assert.deepEqual(top('wall art'), ['Home Decor › Wall art & Posters'])
})

test('descriptions find things by example', () => {
  assert.deepEqual(top('vinyl'), ['Music › Albums'])
  assert.deepEqual(top('lego'), ['Toys › Building sets'])
  assert.deepEqual(top('nerf'), ['Toys › Battle toys'])
  assert.deepEqual(top('katana'), ['Memorabilia & Keepsakes › Props & replicas'])
  assert.deepEqual(top('cornhole'), ['Sports & outdoors › Lawn & yard games'])
  assert.deepEqual(top('mug'), ['Kitchen › Drinkware'])
  assert.deepEqual(top('mugs'), ['Kitchen › Drinkware']) // plural
  assert.deepEqual(top('popcorn'), ['Kitchen › Popcorn & snack ware'])
  assert.ok(all('pokemon').includes('Games & Puzzles › Trading card games')) // accent-insensitive
})

test('"not for" pointers do not match: they point away from the category', () => {
  assert.ok(!all('cornhole').includes('Games & Puzzles'))
  assert.ok(!all('popcorn').includes('Kitchen › Drinkware'))
  assert.ok(!all('quilt').includes('Family photos & documents'))
  assert.equal(top('quilt')[0], 'Clothing & Linens › Blankets, throws & quilts')
})

test('every word has to match somewhere', () => {
  assert.deepEqual(top('switch case'), ['Video Games › Accessories'])
  assert.deepEqual(all('xyzzy'), [])
})

test("a user's own category shows its full path and is found by name", () => {
  const mine = buildEntries([...rows, { id: 'm1', parent_id: 'Books', name: 'Signed first editions', owner_id: 'u1', description: null }])
  const hit = searchCategories(mine, 'signed first')[0]
  assert.equal(hit.path, 'Books › Signed first editions')
  assert.equal(hit.holds, '')
})
