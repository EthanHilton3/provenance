/**
 * A queue of photos to upload to one item, one at a time, with progress and a per-photo error you can retry.
 * Add uses it before the item exists (files wait until `run(itemId)`); Detail runs it straight away.
 */
import { reactive } from 'vue'
import { api } from './backend'

let seq = 0

export function useUploads() {
  const state = reactive({ list: [] })

  function add(files) {
    for (const file of files) {
      state.list.push({
        key: ++seq,
        file,
        name: file.name,
        // Chrome and Firefox can't show HEIC; the row falls back to the file name. The server converts it anyway.
        preview: /^image\/(jpeg|png|webp|gif)$/.test(file.type) ? URL.createObjectURL(file) : null,
        status: 'waiting', // waiting | uploading | processing | done | error
        progress: 0,
        error: '',
      })
    }
  }

  function remove(entry) {
    if (entry.preview) URL.revokeObjectURL(entry.preview)
    state.list = state.list.filter((e) => e !== entry)
  }

  /** Uploads everything not yet done. Resolves with the number that failed (0 = all good). */
  async function run(itemId, onDone) {
    for (const entry of state.list) {
      if (entry.status === 'done') continue
      entry.status = 'uploading'
      entry.progress = 0
      entry.error = ''
      try {
        const photo = await api.uploadPhoto(itemId, entry.file, (f) => {
          entry.progress = f
          // Once the bytes are up, the server still resizes and cleans the photo.
          if (f >= 1) entry.status = 'processing'
        })
        entry.status = 'done'
        entry.progress = 1
        onDone?.(photo, entry)
      } catch (e) {
        entry.status = 'error'
        entry.error = e.message
      }
    }
    return state.list.filter((e) => e.status === 'error').length
  }

  function clearDone() {
    for (const e of state.list) if (e.status === 'done' && e.preview) URL.revokeObjectURL(e.preview)
    state.list = state.list.filter((e) => e.status !== 'done')
  }

  const busy = () => state.list.some((e) => e.status === 'uploading' || e.status === 'processing')

  return { state, add, remove, run, clearDone, busy }
}
