/**
 * Item editing rules that don't need a screen: which fields the S7 forms edit, how an edit becomes a PATCH, and
 * what differs between two versions of an item (for the "changed since you loaded it" panel).
 */

export const CONDITIONS = [
  ['new', 'New'],
  ['like_new', 'Like new'],
  ['very_good', 'Very good'],
  ['good', 'Good'],
  ['fair', 'Fair'],
  ['poor', 'Poor'],
]
const CONDITION_LABEL = Object.fromEntries(CONDITIONS)

/**
 * The item columns the forms edit, with their labels. `attributes` (the category's fields) is handled per key.
 * Franchise, brand and signed-by are columns because every item has them and they are searched across categories.
 */
export const ITEM_FIELDS = [
  ['name', 'Name'],
  ['category_id', 'Category'],
  ['franchise', 'Franchise / series'],
  ['brand', 'Brand / maker'],
  ['signed_by', 'Signed by'],
  ['condition_grade', 'Condition'],
  ['sealed', 'Sealed'],
  ['acquired_on', 'Acquired'],
  ['source', 'Where from'],
  ['notes', 'Notes'],
]
// sealed: true, false, or null for "not recorded" (S10: the AI often can't tell, and a guess must not become a fact).
const NULLABLE = new Set(['condition_grade', 'acquired_on', 'source', 'notes', 'franchise', 'brand', 'signed_by', 'sealed'])
/** The columns in the form's "More details" section. */
export const MORE_DETAILS = ['franchise', 'brand', 'signed_by']

const isEmpty = (v) => v === null || v === undefined || (typeof v === 'string' && v.trim() === '')
/** Equal for editing purposes: blank text and null are the same, and so are "3" and 3. */
export function same(a, b) {
  if (isEmpty(a) && isEmpty(b)) return true
  if (isEmpty(a) || isEmpty(b)) return false
  if (typeof a === 'string' || typeof b === 'string') return String(a).trim() === String(b).trim()
  return a === b
}

/** A blank form for a new item. */
export function emptyDraft(categoryId = '') {
  return { name: '', category_id: categoryId, franchise: '', brand: '', signed_by: '', condition_grade: '', sealed: null,
    acquired_on: '', source: '', notes: '', attributes: {} }
}

/** An editable copy of a saved item. */
export function draftFrom(item) {
  const d = {}
  for (const [k] of ITEM_FIELDS) d[k] = item[k] ?? (k === 'sealed' ? null : '')
  d.attributes = { ...(item.attributes || {}) }
  return d
}

function clean(key, value) {
  if (typeof value === 'string') value = value.trim()
  if (NULLABLE.has(key) && isEmpty(value)) return null
  return value
}

/** Category field values with blanks dropped, so an emptied field is removed rather than stored as "". */
export function cleanAttributes(attrs) {
  const out = {}
  for (const [k, v] of Object.entries(attrs || {})) {
    if (!isEmpty(v)) out[k] = typeof v === 'string' ? v.trim() : v
  }
  return out
}

/** The body for POST /api/items. */
export function createBody(draft) {
  const body = {}
  for (const [k] of ITEM_FIELDS) body[k] = clean(k, draft[k])
  body.attributes = cleanAttributes(draft.attributes)
  return body
}

/**
 * The PATCH body for the edits in `draft` (compared with `base`, the item as it was loaded), applied on top of
 * `onto`. Normally `onto` is `base`. After a 409, `onto` is the current row: only the fields you changed are sent,
 * so the other person's changes to other fields survive, and their version is used. Null when nothing changed.
 */
export function buildPatch(base, draft, onto = base) {
  const patch = {}
  for (const [k] of ITEM_FIELDS) {
    if (!same(draft[k], base[k])) patch[k] = clean(k, draft[k])
  }
  const before = base.attributes || {}
  const after = draft.attributes || {}
  const changedKeys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => !same(before[k], after[k]))
  if (changedKeys.length) {
    const attrs = { ...(onto.attributes || {}) }
    for (const k of changedKeys) {
      if (isEmpty(after[k])) delete attrs[k]
      else attrs[k] = typeof after[k] === 'string' ? after[k].trim() : after[k]
    }
    patch.attributes = attrs
  }
  if (!Object.keys(patch).length) return null
  patch.version = onto.version
  return patch
}

/**
 * What differs between two versions of an item, as display rows: `{key, label, from, to}`. Category field keys
 * come out as `attributes.<key>`; `labelFor(key)` names them (the category's field label), else the key is used.
 */
export function differences(a, b, labelFor = () => null) {
  const rows = []
  for (const [k, label] of ITEM_FIELDS) {
    if (!same(a[k], b[k])) rows.push({ key: k, label, from: a[k], to: b[k] })
  }
  const aa = a.attributes || {}
  const bb = b.attributes || {}
  for (const k of new Set([...Object.keys(aa), ...Object.keys(bb)])) {
    if (!same(aa[k], bb[k])) rows.push({ key: `attributes.${k}`, label: labelFor(k) || k, from: aa[k], to: bb[k] })
  }
  return rows
}

/** A value as words for reading, not editing. */
export function display(key, value, { categoryName } = {}) {
  if (isEmpty(value)) return '—'
  if (key === 'category_id') return categoryName ? categoryName(value) : value
  if (key === 'condition_grade') return CONDITION_LABEL[value] || value
  if (key === 'sealed') return value ? 'Sealed' : 'Opened'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (key === 'acquired_on') {
    const d = new Date(`${value}T00:00:00`)
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  }
  return String(value)
}
