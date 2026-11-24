/**
 * Categories change rarely, so they are loaded once per session. Names are shown as a path ("Books › Novels")
 * because several children share a name ("Other").
 */
import { reactive } from 'vue'
import { api } from './backend'

const state = reactive({ list: [], byId: {}, loaded: false })
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
    // Parents first, each followed by its children, for the picker.
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

export const categories = state
