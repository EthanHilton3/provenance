<template>
  <div class="stack">
    <div class="head">
      <h1>My things</h1>
      <p v-if="items.length" class="muted small">
        {{ items.length }} {{ items.length === 1 ? 'item' : 'items' }}{{ next ? ' loaded so far' : '' }}
        in {{ groups.length }} {{ groups.length === 1 ? 'category' : 'categories' }}
      </p>
    </div>

    <p v-if="error" class="notice notice-error" role="alert">
      {{ error }} <button class="btn btn-quiet btn-sm" @click="reload">Try again</button>
    </p>

    <div v-if="loading && !items.length" class="muted" aria-busy="true">Loading your items…</div>

    <section v-else-if="!items.length && !error" class="empty card card-pad">
      <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
        <rect x="8" y="14" width="40" height="32" rx="6" fill="none" stroke="currentColor" stroke-width="2" />
        <path d="M8 24h40M22 14v-4h12v4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
      <h2>Nothing catalogued yet</h2>
      <p class="muted">Start with one thing you'd hate to lose track of: a game, a book, a gift. Add a photo so you'll know it at a glance.</p>
      <RouterLink to="/items/new" class="btn btn-primary">Add your first item</RouterLink>
    </section>

    <section v-for="g in groups" :key="g.id" class="group card">
      <button class="group-head" :aria-expanded="!collapsed.has(g.id)" :aria-controls="`g-${g.id}`" @click="toggle(g.id)">
        <span class="chev" :class="{ open: !collapsed.has(g.id) }" aria-hidden="true">›</span>
        <span class="gname">
          <span v-if="g.parent" class="parent">{{ g.parent }} ›</span>
          {{ g.name }}
        </span>
        <span class="count">{{ g.items.length }}</span>
      </button>
      <ul v-show="!collapsed.has(g.id)" :id="`g-${g.id}`" class="list">
        <li v-for="it in g.items" :key="it.id">
          <RouterLink :to="`/items/${it.id}`" class="item" v-visible="() => wantCover(it.id)">
            <img v-if="covers[it.id]" :src="covers[it.id]" alt="" class="thumb" loading="lazy" />
            <span v-else class="thumb blank" aria-hidden="true">{{ initial(it.name) }}</span>
            <span class="text">
              <span class="name">{{ it.name }}</span>
              <span v-if="subline(it)" class="sub">{{ subline(it) }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <button v-if="next" class="btn btn-soft btn-block" :disabled="loading" @click="loadMore">
      {{ loading ? 'Loading…' : 'Load more' }}
    </button>

    <RouterLink v-if="items.length" to="/items/new" class="btn btn-primary fab">+ Add item</RouterLink>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../lib/backend'
import { categories, loadCategories } from '../lib/categories'
import { covers, wantCover } from '../lib/photos'
import { display } from '../lib/item'

const PAGE = 50
const items = ref([])
const next = ref(null)
const loading = ref(false)
const error = ref('')

async function fetchPage(cursor) {
  loading.value = true
  error.value = ''
  try {
    const [page] = await Promise.all([api.listItems({ limit: PAGE, cursor }), loadCategories()])
    items.value = cursor ? [...items.value, ...page.items] : page.items
    next.value = page.next
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
const reload = () => fetchPage(null)
const loadMore = () => fetchPage(next.value)
onMounted(reload)

const groups = computed(() => {
  const byCat = new Map()
  for (const it of items.value) {
    if (!byCat.has(it.category_id)) byCat.set(it.category_id, [])
    byCat.get(it.category_id).push(it)
  }
  return [...byCat].map(([id, list]) => {
    const c = categories.byId[id]
    const parent = c?.parent_id ? categories.byId[c.parent_id]?.name : null
    return { id, name: c?.name ?? 'Unknown category', parent, sort: `${parent ?? c?.name ?? '~'} ${parent ? c.name : ''}`, items: list }
  }).sort((a, b) => a.sort.localeCompare(b.sort))
})

// Which groups are folded away, remembered on this device.
const KEY = 'provenance.collapsed'
const collapsed = reactive(new Set(readCollapsed()))
function readCollapsed() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]') } catch { return [] }
}
function toggle(id) {
  collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id)
  try { localStorage.setItem(KEY, JSON.stringify([...collapsed])) } catch { /* private mode */ }
}

const initial = (name) => (name || '?').trim().charAt(0).toUpperCase()
function subline(it) {
  return [it.condition_grade && display('condition_grade', it.condition_grade), it.sealed && 'Sealed', it.source]
    .filter(Boolean).join(' · ')
}

// Ask for an item's thumbnail only once its row is on screen (collapsed groups never ask).
const observer = typeof IntersectionObserver !== 'undefined'
  ? new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target._onVisible?.()
          observer.unobserve(e.target)
        }
      }
    }, { rootMargin: '200px' })
  : null
const vVisible = {
  mounted(el, { value }) {
    if (!observer) return value()
    el._onVisible = value
    observer.observe(el)
  },
  unmounted(el) { observer?.unobserve(el) },
}
</script>

<style scoped>
.head { display: grid; gap: 4px; }
.empty { display: grid; gap: 12px; justify-items: center; text-align: center; padding: 32px 20px; color: var(--muted); }
.empty h2 { color: var(--text); font-family: var(--font-title); font-size: 1.25rem; }
.empty p { max-width: 34ch; }

.group { overflow: hidden; }
.group-head {
  display: flex; align-items: center; gap: 10px; width: 100%; min-height: 52px; padding: 0 16px;
  border: 0; background: transparent; color: var(--text); font: 600 1rem var(--font-ui); text-align: left; cursor: pointer;
}
.chev { display: inline-block; width: 12px; color: var(--muted); font-size: 1.3rem; line-height: 1; transition: transform 0.15s; }
.chev.open { transform: rotate(90deg); }
.gname { flex: 1; min-width: 0; }
.parent { color: var(--muted); font-weight: 500; }
.count {
  min-width: 28px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2);
  color: var(--muted); font-size: 0.85rem; text-align: center;
}

.list { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--line); }
.list li + li { border-top: 1px solid var(--line); }
.item { display: flex; align-items: center; gap: 12px; min-height: 64px; padding: 8px 16px; color: inherit; text-decoration: none; }
.item:hover { background: var(--surface-2); }
.thumb { width: 48px; height: 48px; flex: none; border-radius: 8px; object-fit: cover; background: var(--surface-2); }
.blank { display: grid; place-items: center; color: var(--faint); font-family: var(--font-title); font-size: 1.2rem; }
.text { display: grid; min-width: 0; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { color: var(--muted); font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
