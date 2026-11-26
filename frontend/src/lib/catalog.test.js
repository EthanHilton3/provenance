import assert from 'node:assert/strict'
import { test } from 'node:test'
import { catalogKind, catalogQuery, needsChoice, releaseBody, resolveRelease, splitYear, workKind } from './catalog.js'

const byId = {
  m: { id: 'm', name: 'Movies & TV', parent_id: null, owner_id: null },
  d: { id: 'd', name: 'Discs', parent_id: 'm', owner_id: null },
  b: { id: 'b', name: 'Books', parent_id: null, owner_id: null },
  mg: { id: 'mg', name: 'Manga', parent_id: 'b', owner_id: null },
  v: { id: 'v', name: 'Video Games', parent_id: null, owner_id: null },
  g: { id: 'g', name: 'Games', parent_id: 'v', owner_id: null },
  c: { id: 'c', name: 'Controllers', parent_id: 'v', owner_id: null },
  k: { id: 'k', name: 'Kitchen', parent_id: null, owner_id: null },
  mine: { id: 'mine', name: 'My discs', parent_id: 'm', owner_id: 'u1' },
}

test('which categories use a catalog', () => {
  assert.equal(catalogKind('d', byId), 'screen')
  assert.equal(catalogKind('d', byId, { catalog: 'tmdb_movie' }), 'movie')
  assert.equal(catalogKind('d', byId, { catalog: 'tmdb_tv' }), 'tv')
  assert.equal(catalogKind('mg', byId), 'book')
  assert.equal(catalogKind('b', byId), 'book')
  assert.equal(catalogKind('g', byId), 'game')         // shared, but no catalog search
  assert.equal(catalogKind('c', byId), null)           // hardware: no
  assert.equal(catalogKind('k', byId), null)
  assert.equal(catalogKind('mine', byId), null)        // a user's own category: private, skipped
  assert.equal(catalogKind('', byId), null)
})

test('the search title comes from the card, with the year split off', () => {
  assert.deepEqual(splitYear('Princess Mononoke (1997)'), { title: 'Princess Mononoke', year: 1997 })
  const card = { catalog: 'tmdb_movie', catalog_query: 'Spirited Away (2001)', name: 'Spirited Away Steelbook' }
  assert.deepEqual(catalogQuery({ card, draft: { name: 'x' }, kind: 'movie' }), { title: 'Spirited Away', kind: 'movie', year: 2001, isbn: null })
  assert.equal(catalogQuery({ card: { catalog: 'none', catalog_query: 'mug' }, draft: { name: 'The Hobbit' }, kind: 'book' }).title, 'The Hobbit')
  assert.equal(catalogQuery({ draft: { name: 'x' }, kind: 'movie', title: 'Typed again' }).title, 'Typed again')
})

test('ISBN from the field or a book barcode, for books only', () => {
  assert.equal(catalogQuery({ draft: { name: 'x', attributes: { isbn: '978-0-547-92822-7' } }, kind: 'book' }).isbn, '9780547928227')
  assert.equal(catalogQuery({ draft: { name: 'x' }, kind: 'book', barcode: '9780547928227' }).isbn, '9780547928227')
  assert.equal(catalogQuery({ draft: { name: 'x' }, kind: 'movie', barcode: '9780547928227' }).isbn, null)
  assert.equal(catalogQuery({ draft: { name: 'x' }, kind: 'book', barcode: '0883929704736' }).isbn, null)
})

const draft = {
  name: ' Spirited Away (Steelbook) ', category_id: 'd', notes: 'from grandma', price_paid: '20', occasion_id: 'o1',
  giver_id: 'p1', location: 'shelf', condition_grade: 'good',
  attributes: { format: 'Blu-ray', edition: 'Steelbook', disc_count: 2, region: 'A' },
}

test('a shared release carries catalog facts only', () => {
  const body = releaseBody(draft, { choice: 'tmdb_movie:129', query: { title: 'Spirited Away', year: 2001 }, kind: 'movie' })
  assert.deepEqual(body, { title: 'Spirited Away (Steelbook)', format: 'Blu-ray', edition: 'Steelbook', barcode: null,
    work: { ref: 'tmdb_movie:129' }, declined: [] })
  const text = JSON.stringify(body)
  for (const secret of ['grandma', '20', 'o1', 'p1', 'shelf', 'good']) assert.ok(!text.includes(secret), secret)
})

test('a steelbook is part of the shared edition; a standard case is not', () => {
  const ed = (attributes) => releaseBody({ name: 'x', attributes }).edition
  assert.equal(ed({ packaging: 'Steelbook' }), 'Steelbook')
  assert.equal(ed({ edition: 'Limited', packaging: 'Steelbook' }), 'Limited, Steelbook')
  assert.equal(ed({ edition: 'Steelbook', packaging: 'steelbook' }), 'Steelbook')
  assert.equal(ed({ edition: 'Extended', packaging: 'Standard case' }), 'Extended')
  assert.equal(ed({}), null)
})

test('"none of these" makes a new work from the search title', () => {
  const body = releaseBody(draft, { choice: 'none', query: { title: 'Spirited Away', year: 2001 }, kind: 'screen', declined: ['r1'] })
  assert.deepEqual(body.work, { new: { title: 'Spirited Away', year: 2001, kind: 'movie' } })
  assert.deepEqual(body.declined, ['r1'])
  const game = releaseBody({ name: 'Zelda', attributes: { platform: 'Switch' } }, { kind: 'game', barcode: '0045496906788' })
  assert.equal(game.format, 'Switch')
  assert.equal(game.barcode, '0045496906788')
  assert.deepEqual(game.work, { new: { title: 'Zelda', year: null, kind: 'game' } })
  assert.equal(workKind('tv'), 'tv')
})

test('sharing waits for a choice when the catalog offered some', () => {
  const result = { status: 'ok', candidates: [{ ref: 'tmdb_tv:246' }] }
  assert.equal(needsChoice({ share: true, kind: 'tv', choice: null, result }), true)
  assert.equal(needsChoice({ share: true, kind: 'tv', choice: 'none', result }), false)
  assert.equal(needsChoice({ share: false, kind: 'tv', choice: null, result }), false)
  assert.equal(needsChoice({ share: true, kind: 'game', choice: null, result: null }), false)
  assert.equal(needsChoice({ share: true, kind: 'tv', choice: null, result: { status: 'unavailable', candidates: [] } }), false)
})

test('resolveRelease reads each answer', async () => {
  const api = (r) => ({ createRelease: async () => r })
  assert.deepEqual(await resolveRelease(api({ status: 'created', release: { id: 'r' } }), {}), { releaseId: 'r', existing: false })
  assert.deepEqual(await resolveRelease(api({ status: 'existing', release: { id: 'r' } }), {}), { releaseId: 'r', existing: true })
  assert.deepEqual(await resolveRelease(api({ status: 'similar', similar: [{ id: 's' }] }), {}), { similar: [{ id: 's' }] })
  assert.ok((await resolveRelease(api({ status: 'unavailable', message: 'down' }), {})).message === 'down')
})
