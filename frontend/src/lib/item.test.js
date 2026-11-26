import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildPatch, createBody, differences, draftFrom, emptyDraft } from './item.js'

const loaded = {
  id: 'i1', version: 3, name: 'Spirited Away', category_id: 'c1', condition_grade: 'good', sealed: false,
  acquired_on: null, source: null, notes: null, attributes: { format: 'Blu-ray', region: 'A' },
}

test('no edits means no PATCH', () => {
  assert.equal(buildPatch(loaded, draftFrom(loaded)), null)
})

test('only changed fields are sent, with the loaded version; blanks become null', () => {
  const draft = { ...draftFrom(loaded), name: ' Spirited Away (4K) ', source: '   ', notes: 'Steelbook' }
  assert.deepEqual(buildPatch(loaded, draft), { name: 'Spirited Away (4K)', notes: 'Steelbook', version: 3 })
})

test('an emptied category field is removed, not stored as an empty string', () => {
  const draft = draftFrom(loaded)
  draft.attributes.region = ''
  assert.deepEqual(buildPatch(loaded, draft), { attributes: { format: 'Blu-ray' }, version: 3 })
})

test('after a 409, saving on top keeps their other changes and uses their version', () => {
  // I changed the name and the format; they changed the condition and the region.
  const draft = { ...draftFrom(loaded), name: 'Mine', attributes: { ...loaded.attributes, format: '4K UHD' } }
  const current = { ...loaded, version: 4, condition_grade: 'like_new', attributes: { format: 'Blu-ray', region: 'B' } }
  assert.deepEqual(buildPatch(loaded, draft, current), {
    name: 'Mine',
    attributes: { format: '4K UHD', region: 'B' }, // their region survives
    version: 4,
  })
})

test('differences lists their changes with field labels', () => {
  const current = { ...loaded, version: 4, condition_grade: 'like_new', attributes: { format: 'Blu-ray', region: 'B', discs: 2 } }
  const rows = differences(loaded, current, (k) => ({ region: 'Region' })[k])
  assert.deepEqual(rows, [
    { key: 'condition_grade', label: 'Condition', from: 'good', to: 'like_new' },
    { key: 'attributes.region', label: 'Region', from: 'A', to: 'B' },
    { key: 'attributes.discs', label: 'discs', from: undefined, to: 2 },
  ])
})

test('a number typed as text matches the saved number', () => {
  const item = { ...loaded, attributes: { disc_count: 2 } }
  const draft = { ...draftFrom(item), attributes: { disc_count: '2' } }
  assert.equal(buildPatch(item, draft), null)
})

test('createBody drops blanks; sealed starts as not recorded', () => {
  const d = { ...emptyDraft('c1'), name: 'Lamp', attributes: { brand: '', model: 'X1' } }
  assert.deepEqual(createBody(d), {
    name: 'Lamp', category_id: 'c1', franchise: null, brand: null, signed_by: null, condition_grade: null, sealed: null,
    acquired_on: null, source: null, notes: null, attributes: { model: 'X1' },
  })
})

// Franchise, brand and signed-by are item columns, edited like name or notes.
const signed = { ...loaded, franchise: 'Studio Ghibli', brand: null, signed_by: 'Hayao Miyazaki' }

test('the new columns are part of the draft and the create body, blanks as null', () => {
  const d = { ...emptyDraft('c1'), name: 'Poster', franchise: ' Zelda ', brand: '  ', signed_by: 'Eiji Aonuma' }
  const body = createBody(d)
  assert.equal(body.franchise, 'Zelda')
  assert.equal(body.brand, null)
  assert.equal(body.signed_by, 'Eiji Aonuma')
  const draft = draftFrom(signed)
  assert.equal(draft.franchise, 'Studio Ghibli')
  assert.equal(draft.brand, '') // null becomes an empty input
})

test('editing a new column sends only that column; emptying it sends null', () => {
  assert.equal(buildPatch(signed, draftFrom(signed)), null)
  assert.deepEqual(buildPatch(signed, { ...draftFrom(signed), brand: 'Nintendo' }), { brand: 'Nintendo', version: 3 })
  assert.deepEqual(buildPatch(signed, { ...draftFrom(signed), signed_by: ' ' }), { signed_by: null, version: 3 })
})

test('after a 409, their change to a new column survives saving on top', () => {
  const draft = { ...draftFrom(signed), brand: 'Mine' }
  const current = { ...signed, version: 4, franchise: 'Ghibli Museum' }
  assert.deepEqual(buildPatch(signed, draft, current), { brand: 'Mine', version: 4 })
  assert.deepEqual(differences(signed, current), [
    { key: 'franchise', label: 'Franchise / series', from: 'Studio Ghibli', to: 'Ghibli Museum' },
  ])
  assert.deepEqual(differences(signed, draft).map((d) => d.key), ['brand'])
})
