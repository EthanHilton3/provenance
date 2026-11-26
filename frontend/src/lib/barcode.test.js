import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  LISTING_CHECK, agree, barcodeKind, canonical, categoryForKind, checksumValid, displayBarcode, editionQuestion,
  lookupToDraft, missText, parseBarcode, pickCode, upceToUpca,
} from './barcode.js'
import { createBody } from './item.js'
import { confirmItem } from './intake.js'

const DISCS = [
  { key: 'kind', label: 'Movie or TV', type: 'choice', options: ['Movie', 'TV', 'Other'] },
  { key: 'format', label: 'Format', type: 'choice', options: ['4K UHD', 'Blu-ray', 'DVD', 'HD DVD', 'Other'] },
  { key: 'edition', label: 'Edition', type: 'text' },
  { key: 'packaging', label: 'Packaging', type: 'choice', options: ['Standard case', 'Steelbook', 'Slipcover', 'Box set', 'Other'] },
]
const GAMES = [
  { key: 'platform', label: 'Platform', type: 'choice', options: ['GameCube', 'Switch', 'Switch 2', 'PS5', 'Other'] },
  { key: 'edition', label: 'Edition', type: 'text' },
]
const CATS = [
  { id: 'mtv', name: 'Movies & TV', parent_id: null }, { id: 'discs', name: 'Discs', parent_id: 'mtv' },
  { id: 'vg', name: 'Video Games', parent_id: null }, { id: 'games', name: 'Games', parent_id: 'vg' },
  { id: 'books', name: 'Books', parent_id: null }, { id: 'mine', name: 'Discs', parent_id: 'mtv', owner_id: 'u' },
]
const LOTR = {
  status: 'found', source: 'upcitemdb', barcode: '0883929704736',
  release: { id: 'rel-1', barcode: '0883929704736', title: 'The Lord of the Rings Trilogy (Extended & Theatrical)(4K/UHD)', publisher: 'Warner', edition: null, format: null },
  hints: { kind: 'movie', format: '4K UHD', platform: null, editions: ['Extended & Theatrical'] },
}

test('check digits match the backend (and the barcode test)', () => {
  for (const ok of ['036000291452', '0036000291452', '4006381333931', '96385074', '01234565', '9780306406157', '045496900397', '883929704736'])
    assert.ok(checksumValid(ok), ok)
  for (const bad of ['036000291453', '045496600397', '12345', 'abc', ''])
    assert.ok(!checksumValid(bad), bad)
  assert.equal(upceToUpca('01234565'), '012345000065')
  assert.equal(barcodeKind('9780306406157'), 'ISBN-13')
})

test('UPC-A and EAN-13 spellings of one product are one code', () => {
  assert.equal(canonical('036000291452'), '0036000291452')
  assert.equal(canonical('0036000291452'), '0036000291452')
  assert.equal(canonical('00036000291452'), '0036000291452')
  assert.equal(canonical('01234565'), '0012345000065')
  assert.deepEqual(parseBarcode(' 0 36000-29145 2 '), { code: '0036000291452', kind: 'UPC-A' })
})

test('parseBarcode explains what is wrong', () => {
  assert.match(parseBarcode('').error, /Enter/)
  assert.match(parseBarcode('03600029145a').error, /digits only/)
  assert.match(parseBarcode('12345').error, /8, 12, 13 or 14/)
  assert.match(parseBarcode('045496600397').error, /check digit/) // IMG_9427 as the model misread it
})

test('the camera skips misreads and waits for two frames to agree', () => {
  assert.equal(pickCode([{ rawValue: '045496600397' }]), null)
  assert.deepEqual(pickCode([{ rawValue: 'junk' }, { rawValue: '883929704736' }]), { code: '0883929704736', kind: 'UPC-A' })
  let s = { last: null, count: 0 }
  s = agree(s, pickCode([{ rawValue: '883929704736' }]))
  assert.equal(s.accepted, null)
  s = agree(s, null) // a frame with nothing in it doesn't reset
  s = agree(s, pickCode([{ rawValue: '0883929704736' }])) // the same product in its other spelling
  assert.equal(s.accepted.code, '0883929704736')
  s = agree({ last: '0883929704736', count: 1 }, pickCode([{ rawValue: '036000291452' }]))
  assert.equal(s.accepted, null)
})

test('display shows the digits printed on the box', () => {
  assert.equal(displayBarcode('0883929704736'), '883929704736')
  assert.equal(displayBarcode('4006381333931'), '4006381333931')
})

test('a found release becomes a draft linked to it, with the listing format marked and no edition', () => {
  const categoryId = categoryForKind('movie', CATS)
  assert.equal(categoryId, 'discs') // the built-in one, not the user's own "Discs"
  const { draft, flags } = lookupToDraft(LOTR, DISCS, { categoryId })
  assert.equal(draft.release_id, 'rel-1')
  assert.equal(draft.name, LOTR.release.title)
  assert.equal(draft.brand, 'Warner')
  assert.deepEqual(draft.attributes, { barcode: '0883929704736', format: '4K UHD' })
  assert.deepEqual(flags, { 'attributes.format': LISTING_CHECK })
  assert.equal(draft.attributes.edition, undefined, 'the edition is never guessed')
  const body = confirmItem(draft)
  assert.equal(body.release_id, 'rel-1')
  assert.equal(createBody({ ...draft, release_id: '' }).release_id, undefined)
})

test('a game gets its platform; a format the category has no field for is left alone', () => {
  const smash = { ...LOTR, release: { ...LOTR.release, id: 'rel-2', title: 'Super Smash Bros Melee' },
    hints: { kind: 'game', format: null, platform: 'GameCube', editions: [] } }
  assert.equal(categoryForKind('game', CATS), 'games')
  assert.deepEqual(lookupToDraft(smash, GAMES).draft.attributes, { barcode: '0883929704736', platform: 'GameCube' })
  const odd = { ...smash, hints: { ...smash.hints, platform: 'Atari Lynx' } }
  assert.deepEqual(lookupToDraft(odd, GAMES).draft.attributes, { barcode: '0883929704736' })
  assert.equal(categoryForKind(null, CATS), '')
})

test('a release that states its own edition and format is used as is', () => {
  const verified = { ...LOTR, release: { ...LOTR.release, edition: 'Extended', format: 'Blu-ray' } }
  const { draft, flags } = lookupToDraft(verified, DISCS)
  assert.equal(draft.attributes.edition, 'Extended')
  assert.equal(draft.attributes.format, 'Blu-ray')
  assert.deepEqual(flags, {})
})

test('the edition is a one-tap question until answered', () => {
  const { draft } = lookupToDraft(LOTR, DISCS)
  const q = editionQuestion(draft, DISCS, LOTR.hints)
  assert.deepEqual(q.options.map((o) => o.label), ['Extended & Theatrical', 'Standard'])
  assert.equal(q.key, 'attributes.edition')
  assert.equal(editionQuestion({ ...draft, attributes: { edition: 'Standard' } }, DISCS, LOTR.hints), null)
  assert.equal(editionQuestion(draft, [{ key: 'format', type: 'choice' }], LOTR.hints), null) // no Edition field
})

test('miss text', () => {
  assert.match(missText({ status: 'not_found' }), /isn't in the catalog/)
  assert.equal(missText({ status: 'unavailable', message: 'Barcode lookups are used up for today' }), 'Barcode lookups are used up for today.')
  assert.equal(missText({ status: 'unavailable', message: 'Done.' }), 'Done.')
})
