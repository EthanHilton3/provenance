/**
 * Barcode rules that don't need a screen: the check digit (so a misread never reaches the server), the one canonical
 * spelling of a code, and turning a lookup's release into an editable item draft.
 *
 * The check-digit math mirrors backend/app/gtin.py (from the barcode test). The server checks again; this copy only
 * gives instant feedback and lets the camera ignore a frame that read wrong.
 *
 * The release is shared catalog data and its text came from an outside catalog: it only pre-fills a draft that the
 * owner edits, and it is shown as text, never as HTML. Format and platform come from words in the listing's title, so
 * they are marked to check. The edition is never filled in: the listing rarely says it reliably, so it is a one-tap
 * question with the listing's edition words as answers.
 */
import { emptyDraft } from './item.js'
import { fitValue } from './intake.js'

function mod10(body) {
  let total = 0
  for (let i = 0; i < body.length; i++) total += Number(body[body.length - 1 - i]) * (i % 2 === 0 ? 3 : 1)
  return (10 - (total % 10)) % 10
}

export function upceToUpca(u) {
  const ns = u[0]
  const d = u.slice(1, 7)
  const chk = u[7]
  const last = d[5]
  let body
  if ('012'.includes(last)) body = d.slice(0, 2) + last + '0000' + d.slice(2, 5)
  else if (last === '3') body = d.slice(0, 3) + '00000' + d.slice(3, 5)
  else if (last === '4') body = d.slice(0, 4) + '00000' + d[4]
  else body = d.slice(0, 5) + '0000' + last
  return ns + body + chk
}

export function barcodeKind(digits) {
  if (!/^\d+$/.test(digits)) return null
  switch (digits.length) {
    case 12: return 'UPC-A'
    case 13: return ['978', '979'].includes(digits.slice(0, 3)) ? 'ISBN-13' : 'EAN-13'
    case 8: return '01'.includes(digits[0]) ? 'UPC-E' : 'EAN-8'
    case 14: return 'GTIN-14'
    default: return null
  }
}

export function checksumValid(digits) {
  const kind = barcodeKind(digits)
  if (!kind) return false
  const d = kind === 'UPC-E' ? upceToUpca(digits) : digits
  return mod10(d.slice(0, -1)) === Number(d.at(-1))
}

/** UPC-E -> UPC-A, UPC-A -> EAN-13 (leading 0), GTIN-14 with a leading 0 -> EAN-13. The server's form too. */
export function canonical(digits) {
  let d = barcodeKind(digits) === 'UPC-E' ? upceToUpca(digits) : digits
  if (d.length === 12) d = '0' + d
  else if (d.length === 14 && d[0] === '0') d = d.slice(1)
  return d
}

/** `{code, kind}` for a valid barcode, else `{error}` with words for the person who typed it. */
export function parseBarcode(raw) {
  const text = String(raw ?? '').trim()
  if (!text) return { error: 'Enter the numbers under the barcode' }
  if (!/^\d[\d -]*$/.test(text)) return { error: 'A barcode is digits only' }
  const digits = text.replace(/[ -]/g, '')
  const kind = barcodeKind(digits)
  if (!kind) return { error: 'A barcode has 8, 12, 13 or 14 digits' }
  if (!checksumValid(digits)) return { error: "Those digits don't pass the barcode's check digit; one is probably misread" }
  return { code: canonical(digits), kind }
}

/**
 * The first decoder result that is a valid retail barcode, as {code, kind}, or null. A decoder can return a
 * misread whose check digit fails; that frame is skipped rather than looked up.
 */
export function pickCode(results = []) {
  for (const r of results) {
    const parsed = parseBarcode(r?.rawValue)
    if (parsed.code) return parsed
  }
  return null
}

/**
 * The camera's rule for accepting a code: the same valid code in two frames in a row. One frame can misread a digit
 * and still pass the check digit (rare, but a wrong product is worse than a few more milliseconds).
 * Returns the next state; `accepted` is set once agreed.
 */
export function agree(state, hit) {
  if (!hit) return { last: state.last, count: state.count, accepted: null }
  const count = state.last === hit.code ? state.count + 1 : 1
  return { last: hit.code, count, accepted: count >= 2 ? hit : null }
}

/** The digits as printed on most boxes: a UPC-A shows its 12 digits, not the stored EAN-13 with a leading 0. */
export function displayBarcode(code) {
  return code.length === 13 && code[0] === '0' ? code.slice(1) : code
}

// --- the found release -> an item draft ---------------------------------------------------------------------

/** The lookup's kind -> a built-in [parent, child] category; unknown kinds leave the category for the owner. */
export const KIND_PATH = {
  movie: ['Movies & TV', 'Discs'],
  game: ['Video Games', 'Games'],
  book: ['Books'],
  album: ['Music', 'Albums'],
}

export function categoryForKind(kind, rows = []) {
  const path = KIND_PATH[kind]
  if (!path) return ''
  const builtIn = rows.filter((c) => !c.owner_id)
  const top = builtIn.find((c) => !c.parent_id && c.name === path[0])
  if (!top) return ''
  if (path.length === 1) return top.id
  return builtIn.find((c) => c.parent_id === top.id && c.name === path[1])?.id || ''
}

export const LISTING_CHECK = 'From the store listing, check it'

/**
 * A found lookup -> {draft, flags}. `fields` are the draft category's fields (with inherited ones). The draft keeps
 * `release_id`, so saving links my item to the shared release, and the barcode.
 */
export function lookupToDraft(lookup, fields = [], { categoryId = '', occasionId = '' } = {}) {
  const r = lookup.release
  const h = lookup.hints || {}
  const draft = { ...emptyDraft(categoryId), occasion_id: occasionId || '', release_id: r.id }
  const flags = {}
  draft.name = r.title || ''
  draft.brand = r.publisher || ''
  const attrs = { barcode: lookup.barcode }
  for (const [key, value] of [['format', h.format], ['platform', h.platform]]) {
    if (!value) continue
    const field = fields.find((f) => f.key === key)
    // Only into the category's own field, in its spelling; a format the field doesn't list is left to the owner.
    if (!field || (field.type === 'choice' && !(field.options || []).includes(fitValue(field, value)))) continue
    attrs[key] = fitValue(field, value)
    flags[`attributes.${key}`] = LISTING_CHECK
  }
  // A release's own edition or format (set by hand later, S12) is a fact, not a guess, and wins.
  if (r.format && fields.some((f) => f.key === 'format')) {
    attrs.format = fitValue(fields.find((f) => f.key === 'format'), r.format)
    delete flags['attributes.format']
  }
  if (r.edition && fields.some((f) => f.key === 'edition')) attrs.edition = r.edition
  draft.attributes = attrs
  return { draft, flags }
}

/**
 * The one-tap edition question while the category has an Edition field and it is still empty: the listing's
 * edition words first ("Limited Edition Steelbook"), then Standard. The text field below takes anything else.
 */
export function editionQuestion(draft, fields = [], hints = {}) {
  if (!fields.some((f) => f.key === 'edition')) return null
  const v = draft.attributes?.edition
  if (v !== undefined && v !== null && String(v).trim() !== '') return null
  const options = [...(hints?.editions || []), 'Standard'].map((o) => ({ label: o, value: o }))
  return { key: 'attributes.edition', question: 'Which edition is yours?', options }
}

/** What to tell the owner when there is no release. */
export function missText(lookup) {
  if (lookup.status === 'not_found') return "This barcode isn't in the catalog yet."
  const text = (lookup.message || "The barcode catalog can't be reached right now").trim()
  return /[.!?]$/.test(text) ? text : `${text}.` // the server's messages are phrases; a sentence follows them
}
