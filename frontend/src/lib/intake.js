/**
 * Intake rules that don't need a screen: turning the AI's proposal into an editable item draft, which values to mark
 * as unsure, the one-tap follow-up questions, the group "kind" to category mapping, and when to poll.
 *
 * The proposal is model output. Nothing here trusts it: it only pre-fills a draft that the owner edits and confirms,
 * and the backend validates what is confirmed exactly like a hand-made item.
 *
 * Flags are `{key: reason}`, where key is an ItemForm field ("name", "sealed"...) or "attributes.<key>". They mark
 * values to check, and a flag goes away when the owner changes that value (clearFlags).
 */
import { createBody, emptyDraft } from './item.js'
import { visibleFields } from './fields.js'

// --- group photos: the model's `kind` -> a built-in category ------------------------------------------------

/** [parent, child] or [top-level] by name. null: the owner must choose (a box set can hold anything). */
export const KIND_CATEGORY = {
  'novel or book': ['Books'],
  'manga or comic volume': ['Books', 'Manga'],
  'art book or guide': ['Books'],
  'box set or slipcase set': null,
  'video game': ['Video Games', 'Games'],
  'movie or TV disc set': ['Movies & TV', 'Discs'],
  'amiibo or figure': ['Toys', 'Figures'],
  'trading card or card product': ['Games & Puzzles', 'Trading card games'],
  'board game or puzzle': ['Games & Puzzles', 'Board games'],
  'toy or building set': ['Toys'],
  'wall art or decor': ['Home Decor'],
  'electronics or accessory': ['Electronics'],
  other: ['Other'],
}

/** The built-in category id for a kind, from the category rows (GET /api/categories); '' when none fits. */
export function categoryIdForKind(kind, rows = []) {
  const path = KIND_CATEGORY[kind] === undefined ? KIND_CATEGORY.other : KIND_CATEGORY[kind]
  if (!path) return ''
  const builtIn = rows.filter((c) => !c.owner_id)
  const top = builtIn.find((c) => !c.parent_id && c.name === path[0])
  if (!top) return ''
  if (path.length === 1) return top.id
  return builtIn.find((c) => c.parent_id === top.id && c.name === path[1])?.id || ''
}

// --- putting the model's words into fields -------------------------------------------------------------------

const norm = (s) => String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const blank = (v) => v === undefined || v === null || (typeof v === 'string' && v.trim() === '')

/** The template field a free-text name refers to ("Disc count" or "disc_count" -> disc_count), or null. */
export function fieldFor(name, fields = []) {
  const n = norm(name)
  if (!n) return null
  return fields.find((f) => norm(f.key) === n || norm(f.label) === n) || null
}

/** A key for a value the template doesn't have: "Disc count!" -> "disc_count". */
export function keyFrom(name) {
  return norm(name).replace(/ /g, '_').slice(0, 64)
}

/** The value in the field's own terms: a choice option in its spelling, a number as a number, yes/no as a boolean. */
export function fitValue(field, value) {
  const text = String(value).trim()
  if (!field) return text
  if (field.type === 'choice') return (field.options || []).find((o) => norm(o) === norm(text)) ?? text
  if (field.type === 'number') {
    const n = Number(text.replace(/,/g, ''))
    return text !== '' && Number.isFinite(n) ? n : text
  }
  if (field.type === 'boolean') {
    if (/^(yes|true|y)$/i.test(text)) return true
    if (/^(no|false|n)$/i.test(text)) return false
  }
  return text
}

/** A choice field whose options include this value ("Switch" -> platform), or null. */
function choiceHolding(value, fields) {
  return fields.find((f) => f.type === 'choice' && (f.options || []).some((o) => norm(o) === norm(value))) || null
}

/**
 * Puts `value` in the first of `keys` the category has (or a choice field that lists it, when `byOption`), else
 * under `fallback` as an "other detail". Returns the attribute key used, or null when the value is blank.
 */
function place(attrs, fields, value, keys, fallback, { byOption = false } = {}) {
  if (blank(value)) return null
  let field = (byOption && choiceHolding(value, fields)) || keys.map((k) => fields.find((f) => f.key === k)).find(Boolean)
  if (!fits(field, value)) field = null
  const key = field ? field.key : fallback
  if (blank(attrs[key])) attrs[key] = fitValue(field, value)
  return key
}

/**
 * Whether a value can go in a field without losing anything. Text never goes in a number field: a number input can't
 * show "vols 1-3", and typing over it keeps only the digits (Manga's Volume is a number: one item per volume). Such a
 * value is kept as an other detail instead.
 */
function fits(field, value) {
  return !field || field.type !== 'number' || typeof fitValue(field, value) === 'number'
}

const EDITION_CHECK = 'AI guess: editions are often misread, check it'

/** sealed from the single-item card's condition, and whether it is a guess. */
export function sealedFromCondition(condition) {
  if (condition === 'sealed / new in box') return true
  if (condition === 'opened / used') return false
  return null
}

/**
 * A single-item card -> {draft, flags, question}. `fields` are the card's category fields (category_fields(),
 * inherited ones included); without them every value lands in "other details", which is still editable.
 */
export function cardToDraft(card, fields = [], { occasionId = '' } = {}) {
  const draft = { ...emptyDraft(card?.category_id || ''), occasion_id: occasionId || '' }
  const flags = {}
  if (!card) return { draft, flags, question: '' }
  draft.name = card.name || ''
  draft.brand = card.brand_or_maker || ''
  draft.franchise = card.franchise_or_series || ''
  draft.sealed = sealedFromCondition(card.condition)
  if (card.bundle_contents?.length) draft.notes = `Includes: ${card.bundle_contents.join(', ')}`

  const attrs = {}
  const ed = place(attrs, fields, card.edition_or_model, ['edition', 'model'], 'edition')
  const pf = place(attrs, fields, card.platform_or_format, ['platform', 'format'], 'format', { byOption: true })
  for (const a of card.attributes || []) {
    if (blank(a?.key) || blank(a?.value)) continue
    let field = fieldFor(a.key, fields)
    let key = field ? field.key : keyFrom(a.key)
    if (!fits(field, a.value)) {
      field = null
      key = `${key}_as_written` // not the number field's own key, or the text would land in it after all
    }
    if (key && blank(attrs[key])) attrs[key] = fitValue(field, a.value)
  }
  draft.attributes = attrs

  if (card.confidence === 'low') flags.name = 'The AI was not sure what this is'
  else if (card.confidence === 'medium') flags.name = 'The AI was not sure of the exact product'
  if (ed) flags[`attributes.${ed}`] = EDITION_CHECK
  if (pf && card.confidence !== 'high') flags[`attributes.${pf}`] = 'AI guess, check it'
  if (draft.sealed !== null) flags.sealed = 'AI guess: sealed and opened are easy to mix up'
  return { draft, flags, question: card.ask_user || '' }
}

/**
 * One item from a group photo -> {draft, flags}. `categoryId` is the row's category (from its kind, or the owner's
 * choice) and `fields` its fields.
 */
export function foundToDraft(found, categoryId = '', fields = [], { occasionId = '' } = {}) {
  const draft = { ...emptyDraft(categoryId), occasion_id: occasionId || '' }
  const flags = {}
  draft.name = found.name || ''
  draft.franchise = found.series_or_franchise || ''
  draft.sealed = typeof found.sealed === 'boolean' ? found.sealed : null
  const attrs = {}
  // Books have an author, albums an artist: a creator goes there; anything else is the brand.
  const creatorKey = place(attrs, fields, found.creator_or_maker, ['author', 'artist', 'creators'], '__none')
  if (creatorKey === '__none') {
    delete attrs.__none
    draft.brand = found.creator_or_maker || ''
  }
  const vol = place(attrs, fields, found.volumes_or_count, ['volume', 'issue_or_volume'], 'volumes')
  const ed = place(attrs, fields, found.edition_or_format, ['edition', 'format'], 'edition', { byOption: true })
  draft.attributes = attrs

  if (found.confidence === 'low') flags.name = 'The AI was not sure what this is'
  else if (found.confidence === 'medium') flags.name = 'Check the exact title'
  if (vol) flags[`attributes.${vol}`] = 'AI guess: volume numbers are often misread, check them'
  if (ed) flags[`attributes.${ed}`] = EDITION_CHECK
  if (draft.sealed !== null) flags.sealed = 'AI guess: sealed and opened are easy to mix up'
  return { draft, flags }
}

/** Flags whose value the owner has since changed are dropped: they've looked at it. */
export function clearFlags(before, after, flags) {
  const out = { ...flags }
  for (const key of Object.keys(flags)) {
    const [top, sub] = key.startsWith('attributes.') ? ['attributes', key.slice(11)] : [key, null]
    const a = sub ? before.attributes?.[sub] : before[top]
    const b = sub ? after.attributes?.[sub] : after[top]
    if (a !== b) delete out[key]
  }
  return out
}

// --- one-tap follow-up questions -----------------------------------------------------------------------------

const MAX_CHOICES = 6
// The edition-level details the feasibility tests found the models miss most ("Blu-ray or DVD?") are asked first;
// other short choice fields follow in template order.
const FIRST = ['format', 'platform', 'packaging', 'product_type', 'base_or_expansion']
const rank = (f) => (FIRST.includes(f.key) ? FIRST.indexOf(f.key) : FIRST.length)

/**
 * Up to `max` one-tap questions for what is still missing: sealed when unknown, then the category's empty choice
 * fields with a short list of answers (a 37-option platform list is not one tap). Each is
 * {key, question, options: [{label, value}]}; key is "sealed" or "attributes.<key>".
 */
export function followUps(draft, fields = [], max = 2) {
  const out = []
  if (draft.sealed === null || draft.sealed === undefined) {
    out.push({ key: 'sealed', question: 'Still sealed?', options: [{ label: 'Sealed', value: true }, { label: 'Opened', value: false }] })
  }
  const attrs = draft.attributes || {}
  const candidates = visibleFields(fields, attrs)
    .filter((f) => blank(attrs[f.key]) && f.type === 'choice' && (f.options || []).length > 0 && f.options.length <= MAX_CHOICES)
    .sort((a, b) => rank(a) - rank(b)) // stable: template order within a rank
  for (const f of candidates) {
    if (out.length >= max) break
    out.push({ key: `attributes.${f.key}`, question: `${f.label}?`, options: f.options.map((o) => ({ label: o, value: o })) })
  }
  return out
}

/** The draft with one follow-up answered. */
export function answer(draft, key, value) {
  if (key.startsWith('attributes.')) return { ...draft, attributes: { ...draft.attributes, [key.slice(11)]: value } }
  return { ...draft, [key]: value }
}

// --- confirming ----------------------------------------------------------------------------------------------

/** The item body for POST /api/intake/jobs/{id}/confirm: the same body as a hand-made item, plus its occasion. */
export function confirmItem(draft) {
  return { ...createBody(draft), occasion_id: draft.occasion_id || null }
}

/**
 * A confirm's 422, split per item: `{0: {name: "...", "attributes.volume": "..."}}`, indexed like the items sent.
 * FastAPI reports each as loc ["body", "items", i, field, key?].
 */
export function itemErrors(body) {
  const out = {}
  const d = body && body.detail
  if (!Array.isArray(d)) return out
  for (const e of d) {
    const loc = Array.isArray(e?.loc) ? e.loc : []
    if (loc[0] !== 'body' || loc[1] !== 'items' || typeof loc[2] !== 'number' || typeof loc[3] !== 'string') continue
    const name = loc[3] === 'attributes' && typeof loc[4] === 'string' ? `attributes.${loc[4]}` : loc[3]
    out[loc[2]] ??= {}
    out[loc[2]][name] ??= String(e.msg || 'Not valid').replace(/^Value error, /, '')
  }
  return out
}

/** Grid rows that will be saved: selected, named and with a category. */
export function readyRows(rows) {
  return rows.filter((r) => r.selected && r.draft.name.trim() && r.draft.category_id)
}

// --- polling -------------------------------------------------------------------------------------------------

const PENDING = new Set(['queued', 'processing'])
export const hasPending = (jobs = []) => jobs.some((j) => PENDING.has(j.status))

/** Start quick, slow down while nothing changes, quick again when something does. */
export function nextDelay(previous, changed, { min = 2000, max = 15000 } = {}) {
  if (changed || !previous) return min
  return Math.min(max, Math.round(previous * 1.5))
}

/** A fingerprint of what the list shows, to tell whether a poll changed anything. */
export const jobsKey = (jobs = []) => jobs.map((j) => `${j.id}:${j.status}:${j.attempts}`).join('|')

export function statusText(job) {
  switch (job.status) {
    case 'queued': return job.error ? `Trying again soon. ${job.error}` : 'Waiting for the AI'
    case 'processing': return 'Reading the photo…'
    case 'needs_review': return job.mode === 'group'
      ? `Ready to review: ${job.card?.items?.length ?? 0} found`
      : `Ready to review${job.card?.name ? `: ${job.card.name}` : ''}`
    case 'failed': return job.error || 'The AI could not read this photo'
    case 'done': return 'Saved'
    case 'discarded': return 'Discarded'
    default: return job.status
  }
}
