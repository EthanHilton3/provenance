<!--
  Category picker: type to search category names and descriptions ("mug", "vinyl", "LEGO"); results show
  "Parent › Child" and what the category holds. With nothing typed it lists the whole tree. A parent with children
  reads "(general)": choosing it means the item fits none of the children.

  Contract: v-model is a category id (prop modelValue, emits update:modelValue).

  An ARIA combobox: arrow keys move through the results, Enter chooses, Escape closes. The list sits in the page
  flow, not floating over it, so on a phone it stays above the keyboard and scrolls.
-->
<template>
  <div class="field picker">
    <label :for="inputId" class="label">Category</label>
    <input :id="inputId" ref="input" class="input" type="text" role="combobox" autocomplete="off" autocapitalize="off"
      spellcheck="false" enterkeyhint="search" aria-autocomplete="list" aria-required="true"
      :aria-expanded="open" :aria-controls="listId" :aria-activedescendant="open && results[active] ? optionId(active) : undefined"
      :value="open ? query : selectedLabel" :placeholder="open && selectedLabel ? selectedLabel : 'Search: mug, vinyl, LEGO, quilt…'"
      @focus="openList" @input="onInput" @keydown="onKey" @blur="close" />

    <p v-if="!open && selected?.holds" class="muted small hint">{{ selected.holds }}</p>

    <div v-if="open" class="results">
      <p v-if="!categories.loaded" class="muted small pad">Loading categories…</p>
      <p v-else-if="noMatch" class="muted small pad" role="status">
        Nothing matches “{{ query.trim() }}”. Try another word, or use Other.
      </p>
      <ul :id="listId" role="listbox" aria-label="Categories" class="list">
        <li v-for="(r, i) in results" :id="optionId(i)" :key="r.id" role="option" :aria-selected="r.id === modelValue"
          :class="{ active: i === active, current: r.id === modelValue, child: r.depth > 0 }"
          @mousedown.prevent @mousemove="active = i" @click="choose(r)">
          <span class="path">
            <span v-if="r.parentPath" class="parent">{{ r.parentPath }} ›</span>
            {{ r.name }}<span v-if="r.general" class="general"> (general)</span>
          </span>
          <span v-if="r.holds" class="desc" :class="{ one: browsing }">{{ r.holds }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { categories } from '../lib/categories'
import { searchCategories } from '../lib/categorySearch'

const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])

const uid = `cp${Math.random().toString(36).slice(2, 8)}`
const inputId = `${uid}-input`
const listId = `${uid}-list`
const optionId = (i) => `${uid}-opt-${i}`

const input = ref(null)
const open = ref(false)
const query = ref('')
const active = ref(0)

const selected = computed(() => categories.entries.find((e) => e.id === props.modelValue) || null)
const selectedLabel = computed(() => (selected.value ? selected.value.path + (selected.value.general ? ' (general)' : '') : ''))

const browsing = computed(() => !query.value.trim())
const matches = computed(() => searchCategories(categories.entries, query.value, 60))
const noMatch = computed(() => categories.loaded && !browsing.value && !matches.value.length)
// With no match, offer Other rather than an empty list.
const results = computed(() => (noMatch.value ? categories.entries.filter((e) => e.depth === 0 && e.name === 'Other') : matches.value))

function openList() {
  if (open.value) return
  open.value = true
  query.value = ''
  active.value = Math.max(0, results.value.findIndex((r) => r.id === props.modelValue))
  nextTick(() => {
    // On a phone, bring the field to the top so the list has room above the keyboard.
    if (window.innerWidth < 640) input.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    showActive()
  })
}
function close() {
  open.value = false
  query.value = ''
}
function onInput(e) {
  query.value = e.target.value
  open.value = true
  active.value = 0
}
function choose(r) {
  emit('update:modelValue', r.id)
  close()
  input.value?.blur()
}
function showActive() {
  document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' })
}
function onKey(e) {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    if (!open.value) return openList()
    const n = results.value.length
    if (!n) return
    active.value = (active.value + (e.key === 'ArrowDown' ? 1 : -1) + n) % n
    nextTick(showActive)
  } else if (e.key === 'Enter') {
    if (!open.value) return
    e.preventDefault() // choose, don't submit the form
    const r = results.value[active.value]
    if (r) choose(r)
  } else if (e.key === 'Escape' && open.value) {
    e.preventDefault()
    close()
  }
}
</script>

<style scoped>
.picker { position: relative; }
.hint { margin: 0; }
.results {
  border: 1px solid var(--line); border-radius: 10px; background: var(--surface); overflow: hidden;
}
.pad { margin: 0; padding: 10px 12px; }
.list { list-style: none; margin: 0; padding: 4px 0; max-height: min(55vh, 420px); overflow-y: auto; overscroll-behavior: contain; }
.list li { display: grid; gap: 2px; padding: 10px 12px; min-height: 44px; cursor: pointer; }
.list li.child { padding-left: 24px; }
.list li.active { background: var(--surface-2); }
.list li.current .path { font-weight: 700; }
.path { overflow-wrap: anywhere; }
.parent, .general { color: var(--muted); font-weight: 500; }
.desc {
  color: var(--muted); font-size: 0.85rem; line-height: 1.35;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden;
}
.desc.one { -webkit-line-clamp: 1; line-clamp: 1; }
</style>
