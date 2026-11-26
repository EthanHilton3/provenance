/** The user's occasions, loaded once per session and shared by every picker. */
import { reactive } from 'vue'
import { api } from './backend'

export const occasions = reactive({ list: [], loaded: false, error: '' })
let loading = null

export function loadOccasions() {
  if (occasions.loaded) return Promise.resolve(occasions)
  loading ??= api.listOccasions()
    .then((rows) => { occasions.list = rows; occasions.loaded = true; occasions.error = '' })
    .catch((e) => { occasions.error = e.message })
    .finally(() => { loading = null })
  return loading
}

/** A just-created occasion goes to the top, where the newest usually is. */
export function remember(o) {
  occasions.list = [o, ...occasions.list.filter((x) => x.id !== o.id)]
}

export function occasionName(id) {
  return occasions.list.find((o) => o.id === id)?.name || ''
}
