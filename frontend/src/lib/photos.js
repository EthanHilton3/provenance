/**
 * The first photo of each item for the home screen's thumbnails. The list API doesn't return photos, so this asks
 * for each item's photos as its row scrolls into view, a few at a time, and remembers the answer.
 * (The URLs are signed for an hour; a page left open longer than that will show broken thumbnails until reload.)
 */
import { reactive } from 'vue'
import { api } from './backend'

export const covers = reactive({}) // item id -> url | null
const queue = []
let running = 0
const MAX_AT_ONCE = 4

function pump() {
  while (running < MAX_AT_ONCE && queue.length) {
    const id = queue.shift()
    running++
    api.listPhotos(id)
      .then((photos) => { covers[id] = photos.find((p) => p.url)?.url ?? null })
      .catch(() => { covers[id] = null })
      .finally(() => { running--; pump() })
  }
}

export function wantCover(itemId) {
  if (itemId in covers || queue.includes(itemId)) return
  queue.push(itemId)
  pump()
}

export function forgetCover(itemId) {
  delete covers[itemId]
}

export function setCover(itemId, url) {
  covers[itemId] = url
}
