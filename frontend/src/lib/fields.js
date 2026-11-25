/**
 * Category field rules that don't need a screen. A template field is `{key, label, type, options?, scope?, show_if?}`
 * (supabase/category_tree.json describes the format):
 *   scope    "product" for facts about the product (edition, format, ISBN). Recorded only for now; S11/S12 show a
 *            linked release's values read-only.
 *   show_if  {key, equals}: the field applies only while that other field has that value (Albums: format = Vinyl).
 *
 * A hidden field keeps its value while you edit, so Vinyl → CD → Vinyl loses nothing. cleanForSave() removes it on
 * save. Keys the template doesn't know (an old category's fields) are never removed: they show as "other details".
 */

const blank = (v) => v === undefined || v === null || (typeof v === 'string' && v.trim() === '')

/** Whether `field` applies, given the current values. A field that depends on a hidden field is hidden too. */
export function isVisible(field, values = {}, fields = [], seen = new Set()) {
  const cond = field.show_if
  if (!cond) return true
  if (seen.has(field.key)) return false // a loop in the template: treat as hidden rather than recurse forever
  const value = values[cond.key]
  if (blank(value) || String(value).trim() !== String(cond.equals)) return false
  const parent = fields.find((f) => f.key === cond.key)
  return !parent || isVisible(parent, values, fields, new Set([...seen, field.key]))
}

/** The template fields that apply to these values, in template order. */
export function visibleFields(fields = [], values = {}) {
  return fields.filter((f) => isVisible(f, values, fields))
}

/** The attributes to save: values of template fields that are currently hidden are removed; everything else stays. */
export function cleanForSave(fields = [], attributes = {}) {
  const out = { ...attributes }
  for (const f of fields) {
    if (f.key in out && !isVisible(f, attributes, fields)) delete out[f.key]
  }
  return out
}
