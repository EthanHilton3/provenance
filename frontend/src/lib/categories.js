/**
 * Categories change rarely, so they are loaded once per session. Names are shown as a path ("Kitchen › Drinkware")
 * so a child is never mistaken for another one with a similar name. `entries` is what the picker searches
 * (lib/categorySearch.js).
 */
import { reactive } from 'vue'
import { api } from './backend'
import { buildEntries } from './categorySearch'
import { cleanForSave } from './fields'

const state = reactive({ list: [], entries: [], byId: {}, loaded: false })
let loading = null
const fieldsCache = new Map()

export function categoryPath(id) {
  const c = state.byId[id]
  if (!c) return 'Unknown category'
  const parent = c.parent_id && state.byId[c.parent_id]
  return parent ? `${parent.name} › ${c.name}` : c.name
}

export async function loadCategories() {
  if (state.loaded) return state
  loading ??= api.listCategories().then((rows) => {
    state.byId = Object.fromEntries(rows.map((c) => [c.id, c]))
    state.entries = buildEntries(rows)
    // Parents first, each followed by its children.
    const top = rows.filter((c) => !c.parent_id).sort((a, b) => a.name.localeCompare(b.name))
    state.list = top.map((p) => ({
      ...p,
      children: rows.filter((c) => c.parent_id === p.id).sort((a, b) => a.name.localeCompare(b.name)),
    }))
    state.loaded = true
    return state
  }).finally(() => { loading = null })
  return loading
}

/** The fields a category's items have, inherited ones included. */
export function categoryFields(id) {
  if (!id) return Promise.resolve([])
  if (!fieldsCache.has(id)) {
    fieldsCache.set(id, api.categoryFields(id).catch((e) => { fieldsCache.delete(id); throw e }))
  }
  return fieldsCache.get(id)
}

/**
 * The draft as it should be saved: values of conditional fields that are hidden right now are removed (cleanForSave).
 * If the category's fields can't be loaded, nothing is removed: better to keep a stale value than lose one.
 */
export async function cleanDraft(draft) {
  let fields
  try {
    fields = await categoryFields(draft.category_id)
  } catch {
    return draft
  }
  return { ...draft, attributes: cleanForSave(fields, draft.attributes) }
}

export const categories = state
