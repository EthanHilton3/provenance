import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  KIND_CATEGORY, answer, cardToDraft, categoryIdForKind, clearFlags, confirmItem, fitValue, followUps, foundToDraft,
  hasPending, itemErrors, jobsKey, keyFrom, nextDelay, readyRows, statusText,
} from './intake.js'

// category_fields() for Video Games › Games and Movies & TV › Discs, Books › Manga (inherited fields included).
const GAMES = [
  { key: 'region', label: 'Region', type: 'text' },
  { key: 'platform', label: 'Platform', type: 'choice', options: ['NES', 'Wii', 'Switch', 'Switch 2', 'PS4', 'PS5', 'Xbox', 'PC', 'Other'] },
  { key: 'edition', label: 'Edition', type: 'text' },
  { key: 'completeness', label: 'Completeness', type: 'choice', options: ['Complete in box', 'Complete no box', 'Incomplete', 'Loose item'] },
]
const DISCS = [
  { key: 'kind', label: 'Kind', type: 'choice', options: ['Movie', 'TV', 'Other'] },
  { key: 'format', label: 'Format', type: 'choice', options: ['4K UHD', 'Blu-ray', 'DVD', 'HD DVD', 'Other'] },
  { key: 'edition', label: 'Edition', type: 'text' },
  { key: 'packaging', label: 'Packaging', type: 'choice', options: ['Standard case', 'Steelbook', 'Slipcover', 'Box set', 'Other'] },
  { key: 'disc_count', label: 'Discs', type: 'number' },
]
const MANGA = [
  { key: 'author', label: 'Author', type: 'text' },
  { key: 'format', label: 'Format', type: 'choice', options: ['Hardcover', 'Paperback', 'Mass market', 'Other'] },
  { key: 'edition', label: 'Edition', type: 'text' },
  { key: 'volume', label: 'Volume', type: 'number' }, // a number: one item per volume
]

const CARD = {
  item_count: 1, category: 'Movies & TV > Discs', category_id: 'c-discs', name: 'Spirited Away', brand_or_maker: 'GKIDS',
  franchise_or_series: 'Studio Ghibli', edition_or_model: '25th anniversary', platform_or_format: null,
  attributes: [{ key: 'Disc count', value: '2' }, { key: 'packaging', value: 'steelbook' }, { key: 'Color', value: 'blue' }, { key: '', value: 'x' }],
  condition: 'cannot tell', bundle_contents: ['art cards'], catalog: 'tmdb_movie', catalog_query: 'Spirited Away',
  confidence: 'medium', ask_user: 'Is this the 4K UHD or the Blu-ray?',
}

test('a single card fills the draft in the category\'s own terms', () => {
  const { draft, flags, question } = cardToDraft(CARD, DISCS, { occasionId: 'occ1' })
  assert.equal(draft.name, 'Spirited Away')
  assert.equal(draft.category_id, 'c-discs')
  assert.equal(draft.brand, 'GKIDS')
  assert.equal(draft.franchise, 'Studio Ghibli')
  assert.equal(draft.occasion_id, 'occ1')
  assert.equal(draft.sealed, null) // "cannot tell" is not recorded, never "opened"
  assert.equal(draft.notes, 'Includes: art cards')
  assert.deepEqual(draft.attributes, { edition: '25th anniversary', disc_count: 2, packaging: 'Steelbook', color: 'blue' })
  assert.equal(question, 'Is this the 4K UHD or the Blu-ray?')
  assert.ok(flags.name && flags['attributes.edition'])
  assert.equal(flags.sealed, undefined)
})

test('the platform lands on the choice field, and a sure card flags only the edition and sealed', () => {
  const card = { ...CARD, category_id: 'c-games', confidence: 'high', condition: 'sealed / new in box', edition_or_model: null,
    platform_or_format: 'switch', attributes: [] }
  const { draft, flags } = cardToDraft(card, GAMES)
  assert.equal(draft.attributes.platform, 'Switch')
  assert.equal(draft.sealed, true)
  assert.deepEqual(Object.keys(flags).sort(), ['sealed'])  // sealed is never presented as certain
})

test('without the category fields every value is kept as an other detail', () => {
  const { draft } = cardToDraft({ ...CARD, platform_or_format: 'DVD' })
  assert.deepEqual(draft.attributes, { edition: '25th anniversary', format: 'DVD', disc_count: '2', packaging: 'steelbook', color: 'blue' })
  assert.equal(cardToDraft(null).draft.name, '') // a failed job: a blank card to fill in by hand
})

test('fitValue and keyFrom', () => {
  assert.equal(fitValue({ type: 'number' }, '1,000'), 1000)
  assert.equal(fitValue({ type: 'number' }, 'about 12'), 'about 12')
  assert.equal(fitValue({ type: 'boolean' }, 'Yes'), true)
  assert.equal(fitValue({ type: 'choice', options: ['Blu-ray'] }, 'BLU RAY'), 'Blu-ray')
  assert.equal(fitValue({ type: 'choice', options: ['Blu-ray'] }, 'Laserdisc'), 'Laserdisc')
  assert.equal(keyFrom('  Disc count! '), 'disc_count')
})

const FOUND = {
  name: 'Trigun Maximum', creator_or_maker: 'Yasuhiro Nightow', kind: 'manga or comic volume', series_or_franchise: 'Trigun',
  volumes_or_count: 'vols 1 and 2', edition_or_format: 'Deluxe', text_read_on_item: 'TRIGUN', confidence: 'high',
  position: 'top shelf', sealed: null,
}

test('a group row: creator to author, volumes and edition always marked as unsure', () => {
  const { draft, flags } = foundToDraft(FOUND, 'c-manga', MANGA)
  assert.equal(draft.category_id, 'c-manga')
  // Volume is a number field; a run ("vols 1 and 2") is kept as text beside it, never squeezed into it (the browser
  // walk found typing over it saved 13).
  assert.deepEqual(draft.attributes, { author: 'Yasuhiro Nightow', volumes: 'vols 1 and 2', edition: 'Deluxe' })
  assert.equal(draft.brand, '')
  assert.equal(draft.sealed, null)
  assert.ok(flags['attributes.volumes'] && flags['attributes.edition'])
  assert.equal(flags.name, undefined) // high confidence: the title isn't flagged
  // One volume number does go in the field, as a number, still marked.
  const one = foundToDraft({ ...FOUND, volumes_or_count: '3' }, 'c-manga', MANGA)
  assert.equal(one.draft.attributes.volume, 3)
  assert.ok(one.flags['attributes.volume'])
})

test('a text attribute named like a number field is kept beside it', () => {
  const { draft } = cardToDraft({ ...CARD, edition_or_model: null, attributes: [{ key: 'Volume', value: '1-3' }] }, MANGA)
  assert.deepEqual(draft.attributes, { volume_as_written: '1-3' })
})

test('a group row with no author field: the maker is the brand; a guess at sealed is flagged', () => {
  const { draft, flags } = foundToDraft({ ...FOUND, kind: 'video game', confidence: 'low', sealed: true, volumes_or_count: null,
    edition_or_format: 'Switch' }, 'c-games', GAMES)
  assert.equal(draft.brand, 'Yasuhiro Nightow')
  assert.deepEqual(draft.attributes, { platform: 'Switch' })
  assert.equal(draft.sealed, true)
  assert.ok(flags.name && flags.sealed && flags['attributes.platform'])
})

const ROWS = [
  { id: 'b', name: 'Books', parent_id: null, owner_id: null },
  { id: 'm', name: 'Manga', parent_id: 'b', owner_id: null },
  { id: 'vg', name: 'Video Games', parent_id: null, owner_id: null },
  { id: 'g', name: 'Games', parent_id: 'vg', owner_id: null },
  { id: 'o', name: 'Other', parent_id: null, owner_id: null },
  { id: 'mine', name: 'Manga', parent_id: 'b', owner_id: 'u1' },
]

test('kind to category: built-in only, box sets need a choice, unknown kinds are Other', () => {
  assert.equal(categoryIdForKind('manga or comic volume', ROWS), 'm')
  assert.equal(categoryIdForKind('novel or book', ROWS), 'b')
  assert.equal(categoryIdForKind('video game', ROWS), 'g')
  assert.equal(categoryIdForKind('box set or slipcase set', ROWS), '')
  assert.equal(categoryIdForKind('something new', ROWS), 'o')
  assert.equal(categoryIdForKind('movie or TV disc set', ROWS), '') // not in these rows
  assert.equal(Object.keys(KIND_CATEGORY).length, 13) // every kind in backend/app/ai.py KINDS
})

test('editing a flagged value clears its flag, and only that one', () => {
  const before = { name: 'A', sealed: null, attributes: { edition: 'x', volume: '1' } }
  const flags = { name: 'n', sealed: 's', 'attributes.edition': 'e', 'attributes.volume': 'v' }
  const after = { ...before, sealed: true, attributes: { ...before.attributes, edition: 'Deluxe' } }
  assert.deepEqual(clearFlags(before, after, flags), { name: 'n', 'attributes.volume': 'v' })
})

test('follow-ups: sealed when unknown, then the format before other short choices', () => {
  // Kind comes first in the template, but "Blu-ray or DVD?" is the detail the models miss, so it is asked first.
  const draft = { sealed: null, attributes: {} }
  const qs = followUps(draft, DISCS)
  assert.deepEqual(qs.map((q) => q.key), ['sealed', 'attributes.format'])
  assert.deepEqual(qs[1].options.map((o) => o.value), ['4K UHD', 'Blu-ray', 'DVD', 'HD DVD', 'Other'])
  // Answered: the next questions move up (packaging is also a "first" field; kind follows in template order).
  const next = followUps(answer(answer(draft, 'sealed', false), 'attributes.format', 'DVD'), DISCS)
  assert.deepEqual(next.map((q) => q.key), ['attributes.packaging', 'attributes.kind'])
  // Long lists (the real platform list has 37) are not one tap; text fields never are.
  assert.deepEqual(followUps({ sealed: false, attributes: {} }, GAMES).map((q) => q.key), ['attributes.completeness'])
  assert.deepEqual(followUps({ sealed: true, attributes: {} }, []), [])
})

test('confirmItem is a hand-made item body plus the occasion', () => {
  const { draft } = cardToDraft(CARD, DISCS, { occasionId: 'occ1' })
  const body = confirmItem(draft)
  assert.equal(body.occasion_id, 'occ1')
  assert.equal(body.sealed, null)
  assert.equal(body.signed_by, null)
  assert.ok(!('flags' in body) && !('intake_job_id' in body))
  assert.equal(confirmItem({ ...draft, occasion_id: '' }).occasion_id, null)
})

test('readyRows: selected, named, with a category', () => {
  const row = (selected, name, category_id) => ({ selected, draft: { name, category_id } })
  const rows = [row(true, 'A', 'c'), row(false, 'B', 'c'), row(true, '  ', 'c'), row(true, 'Box set', '')]
  assert.deepEqual(readyRows(rows).map((r) => r.draft.name), ['A'])
})

test('polling: only while something is pending, slower while nothing changes', () => {
  assert.equal(hasPending([{ status: 'needs_review' }, { status: 'failed' }]), false)
  assert.equal(hasPending([{ status: 'needs_review' }, { status: 'queued' }]), true)
  assert.equal(nextDelay(0, false), 2000)
  assert.equal(nextDelay(2000, false), 3000)
  assert.equal(nextDelay(12000, false), 15000)
  assert.equal(nextDelay(15000, true), 2000)
  assert.notEqual(jobsKey([{ id: 1, status: 'queued', attempts: 1 }]), jobsKey([{ id: 1, status: 'queued', attempts: 2 }]))
})

test('status text', () => {
  assert.equal(statusText({ status: 'queued', error: 'The AI service is busy; will retry' }), 'Trying again soon. The AI service is busy; will retry')
  assert.equal(statusText({ status: 'needs_review', mode: 'group', card: { items: [1, 2] } }), 'Ready to review: 2 found')
  assert.equal(statusText({ status: 'failed', error: null }), 'The AI could not read this photo')
})

test('itemErrors splits a confirm 422 by item', () => {
  const body = { detail: [
    { loc: ['body', 'items', 1, 'name'], msg: 'String should have at least 1 character' },
    { loc: ['body', 'items', 1, 'attributes', 'volume', 'str'], msg: 'too long' },
    { loc: ['body', 'items', 0, 'condition_grade'], msg: "Input should be 'new'" },
    { loc: ['body', 'items'], msg: 'List should have at least 1 item' },
  ] }
  assert.deepEqual(itemErrors(body), {
    0: { condition_grade: "Input should be 'new'" },
    1: { name: 'String should have at least 1 character', 'attributes.volume': 'too long' },
  })
  assert.deepEqual(itemErrors({ detail: 'nope' }), {})
})
