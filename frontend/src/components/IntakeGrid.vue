<!--
  The confirmation grid for one group photo: one row per item the AI found, quick to scan on a phone. Tick the rows
  to keep, fix a name inline, answer "sealed?" with one tap, open a row for every field (category included), remove
  rows, add what the AI missed, then save the selected rows together. Each saved item gets the photo.

  Category: from the item's kind (lib/intake.js KIND_CATEGORY), changeable per row; a box set has none until you
  choose. Volume numbers, editions and sealed are always marked as guesses: the tested models miss them often.
-->
<template>
  <div class="grid-review">
    <IntakePhoto :url="job.photo?.url || ''" class="photo" />

    <div class="stack">
      <p v-if="job.status === 'failed'" class="notice notice-warn">
        The AI couldn't read this photo<span v-if="job.error">: {{ job.error.replace(/\.\s*$/, '') }}</span>. Add the items by hand; each gets the photo.
      </p>
      <div v-else class="summary">
        <p><strong>{{ found }} {{ found === 1 ? 'item' : 'items' }} found.</strong> Untick anything you don't want to save.</p>
        <p v-if="unidentified" class="muted small">
          The AI also saw {{ unidentified }} {{ unidentified === 1 ? 'thing' : 'things' }} it couldn't identify. Add
          {{ unidentified === 1 ? 'it' : 'them' }} with "Add an item the AI missed".
        </p>
        <p v-if="notes" class="muted small">AI note: {{ notes }}</p>
      </div>

      <OccasionPicker v-model="occasionId" label="All from an occasion" none-label="No occasion" :disabled="busy || !!already" />

      <div v-if="rows.length" class="row tools">
        <button type="button" class="btn btn-quiet btn-sm" @click="selectAll(true)">Select all</button>
        <button type="button" class="btn btn-quiet btn-sm" @click="selectAll(false)">None</button>
        <span class="spacer" />
        <span class="muted small">{{ selectedCount }} selected</span>
      </div>

      <p v-if="!ready" class="muted" aria-busy="true">Preparing the list…</p>
      <ul v-else class="rows">
        <li v-for="r in rows" :key="r.key" class="r card" :class="{ off: !r.selected, open: r.open, err: rowErrors[r.key] }">
          <label class="pick">
            <input v-model="r.selected" type="checkbox" :aria-label="`Save ${r.draft.name || 'this item'}`" :disabled="busy" />
          </label>
          <div class="main">
            <input v-if="!r.open" class="input name" :class="{ flagged: r.flags.name }" :value="r.draft.name" maxlength="300" placeholder="Name"
              aria-label="Name" :disabled="busy" @input="onRow(r, { ...r.draft, name: $event.target.value })" />
            <div class="meta">
              <button type="button" class="cat" :class="{ missing: !r.draft.category_id }" @click="r.open = true">
                {{ r.draft.category_id ? categoryPath(r.draft.category_id) : 'Pick a category' }}
              </button>
              <button v-for="n in notesFor(r)" :key="n" type="button" class="flag-note as-btn" @click="r.open = true">{{ n }}</button>
            </div>
            <div v-if="r.draft.sealed === null && !r.open" class="sealed">
              <span class="small muted">Sealed?</span>
              <button type="button" class="chip sm" @click="onRow(r, { ...r.draft, sealed: true })">Sealed</button>
              <button type="button" class="chip sm" @click="onRow(r, { ...r.draft, sealed: false })">Opened</button>
            </div>
            <p v-if="r.source" class="where small muted">
              {{ r.source.position }}<template v-if="r.source.text_read_on_item"> · read “{{ r.source.text_read_on_item }}”</template>
            </p>
            <p v-if="rowErrors[r.key]" class="field-error" role="alert">{{ Object.values(rowErrors[r.key])[0] }}</p>
            <div v-if="r.open" class="editor">
              <ItemForm :draft="r.draft" :flags="r.flags" :errors="rowErrors[r.key] || {}" @update:draft="onRow(r, $event)" />
              <button type="button" class="btn btn-soft btn-block" @click="r.open = false">Done</button>
            </div>
          </div>
          <div class="side">
            <button v-if="!r.open" type="button" class="btn btn-quiet btn-sm" :aria-label="`Edit ${r.draft.name || 'this item'}`" @click="r.open = true">Edit</button>
            <button type="button" class="btn btn-quiet btn-sm" :aria-label="`Remove ${r.draft.name || 'this item'}`" :disabled="busy" @click="remove(r)">✕</button>
          </div>
        </li>
      </ul>

      <button type="button" class="btn btn-soft btn-block" :disabled="busy || !!already" @click="addMissed">+ Add an item the AI missed</button>

      <section v-if="already" class="notice notice-info" role="status">
        Already saved, from another tab or an earlier tap:
        <RouterLink v-for="it in already" :key="it.id" :to="`/items/${it.id}`" class="saved-link">{{ it.name }}</RouterLink>
      </section>
      <p v-else-if="error" class="notice notice-error" role="alert">{{ error }}</p>
    </div>

    <div class="bar">
      <template v-if="!already">
        <button type="button" class="btn btn-danger-quiet" :disabled="busy" @click="asking = true">Discard</button>
        <button type="button" class="btn btn-primary" :disabled="busy || !readyCount" @click="save">
          {{ busy ? 'Saving…' : readyCount ? `Save ${readyCount} ${readyCount === 1 ? 'item' : 'items'}` : 'Nothing to save' }}
        </button>
        <p v-if="blocked" class="small hint">{{ blocked }}</p>
      </template>
      <button v-else type="button" class="btn btn-primary next" @click="$emit('finished', { saved: 0 })">Next</button>
    </div>

    <ConfirmSheet :open="asking" title="Discard this photo?" confirm-label="Discard" :busy="busy" :error="discardError"
      @cancel="asking = false; discardError = ''" @confirm="discard">
      The photo and the whole list are deleted. Nothing is saved.
    </ConfirmSheet>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import ConfirmSheet from './ConfirmSheet.vue'
import IntakePhoto from './IntakePhoto.vue'
import ItemForm from './ItemForm.vue'
import OccasionPicker from './OccasionPicker.vue'
import { api } from '../lib/backend'
import { categories, categoryFields, categoryPath, cleanDraft, loadCategories } from '../lib/categories'
import { categoryIdForKind, clearFlags, confirmItem, foundToDraft, itemErrors, readyRows } from '../lib/intake'
import { forgetDraft, loadDraft, saveDraft } from '../lib/intakeDrafts'
import { emptyDraft } from '../lib/item'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['finished'])

const scene = computed(() => (props.job.status === 'needs_review' ? props.job.card : null))
const found = computed(() => scene.value?.items?.length ?? 0)
const unidentified = computed(() => scene.value?.visible_but_unidentifiable ?? 0)
const notes = computed(() => scene.value?.notes || '')

const rows = ref([])
const occasionId = ref(props.job.occasion_id || '')
const ready = ref(false)
let seq = 0

const fieldsOf = (id) => (id ? categoryFields(id).catch(() => []) : Promise.resolve([]))

onMounted(async () => {
  await loadCategories().catch(() => {})
  const kept = loadDraft(props.job.id)
  if (kept?.kind === 'group') {
    rows.value = kept.rows
    occasionId.value = kept.occasionId ?? occasionId.value
    seq = Math.max(0, ...rows.value.map((r) => r.key))
  } else {
    const all = Object.values(categories.byId)
    rows.value = await Promise.all((scene.value?.items || []).map(async (it) => {
      const catId = categoryIdForKind(it.kind, all)
      const { draft, flags } = foundToDraft(it, catId, await fieldsOf(catId))
      return { key: ++seq, source: it, draft, flags, selected: true, open: false }
    }))
  }
  ready.value = true
})

watch([rows, occasionId], () => {
  if (ready.value) saveDraft(props.job.id, { kind: 'group', rows: rows.value, occasionId: occasionId.value })
}, { deep: true })

const SHORT = { name: 'Check title', sealed: 'Sealed is a guess' }
function notesFor(r) {
  return [...new Set(Object.keys(r.flags).map((k) => SHORT[k]
    || (/volume/.test(k) ? 'Check volumes' : k.startsWith('attributes.') ? 'Check edition' : 'Check')))]
}

async function onRow(r, next) {
  const before = r.draft
  r.flags = clearFlags(before, next, r.flags)
  r.draft = next
  // A new category: put the AI's details into that category's fields, keeping everything else you edited.
  if (next.category_id !== before.category_id && r.source) {
    const remade = foundToDraft(r.source, next.category_id, await fieldsOf(next.category_id))
    if (r.draft.category_id !== next.category_id) return // changed again while loading
    r.draft = { ...r.draft, attributes: remade.draft.attributes }
    const kept = Object.fromEntries(Object.entries(r.flags).filter(([k]) => !k.startsWith('attributes.')))
    r.flags = { ...kept, ...Object.fromEntries(Object.entries(remade.flags).filter(([k]) => k.startsWith('attributes.'))) }
  }
}

const selectAll = (on) => { for (const r of rows.value) r.selected = on }
const remove = (r) => { rows.value = rows.value.filter((x) => x !== r) }
function addMissed() {
  rows.value.push({ key: ++seq, source: null, draft: emptyDraft(''), flags: {}, selected: true, open: true })
}

const selectedCount = computed(() => rows.value.filter((r) => r.selected).length)
const readyCount = computed(() => readyRows(rows.value).length)
const blocked = computed(() => {
  const n = rows.value.filter((r) => r.selected && !r.draft.category_id).length
  const m = rows.value.filter((r) => r.selected && !r.draft.name.trim()).length
  const parts = [n && `${n} need a category`, m && `${m} need a name`].filter(Boolean)
  return parts.length ? `${parts.join(', ')}; ${n + m === 1 ? 'it is' : 'they are'} left out until fixed.` : ''
})

const busy = ref(false)
const error = ref('')
const rowErrors = ref({})
const already = ref(null)

async function save() {
  const chosen = readyRows(rows.value)
  if (!chosen.length) return
  busy.value = true
  error.value = ''
  rowErrors.value = {}
  try {
    const items = await Promise.all(chosen.map(async (r) => confirmItem({ ...(await cleanDraft(r.draft)), occasion_id: occasionId.value })))
    const out = await api.confirmIntakeJob(props.job.id, items)
    forgetDraft(props.job.id)
    emit('finished', { saved: out.items.length, items: out.items })
  } catch (e) {
    if (e.status === 409 && e.body?.detail?.job?.status === 'done') {
      forgetDraft(props.job.id)
      already.value = e.body.detail.job.items
      return
    }
    const byIndex = itemErrors(e.body)
    rowErrors.value = Object.fromEntries(Object.entries(byIndex).map(([i, errs]) => [chosen[i].key, errs]))
    for (const r of chosen) if (rowErrors.value[r.key]) r.open = true
    error.value = Object.keys(byIndex).length ? 'Some rows need fixing; they are open above.' : e.message
  } finally {
    busy.value = false
  }
}

const asking = ref(false)
const discardError = ref('')
async function discard() {
  busy.value = true
  discardError.value = ''
  try {
    await api.discardIntakeJob(props.job.id)
    forgetDraft(props.job.id)
    asking.value = false
    emit('finished', { saved: 0 })
  } catch (e) {
    discardError.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.grid-review { display: grid; gap: 16px; padding-bottom: 72px; }
.summary { display: grid; gap: 4px; }
.tools { margin: -8px 0; }
.rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.r { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; gap: 4px 8px; padding: 8px 8px 8px 4px; align-items: start; }
.r.off { opacity: 0.55; }
.r.off.open { opacity: 1; }
.r.err { border-color: var(--danger); }
.pick { display: grid; place-items: center; min-height: var(--tap); cursor: pointer; }
.pick input { width: 22px; height: 22px; accent-color: var(--accent); margin: 0; }
.main { display: grid; gap: 6px; min-width: 0; }
.name { font-weight: 600; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.cat {
  min-height: 32px; padding: 2px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface-2);
  color: var(--text); font: 500 0.85rem var(--font-ui); cursor: pointer; text-align: left;
}
.cat.missing { border: 1px dashed var(--danger); color: var(--danger); background: var(--danger-soft); }
.as-btn { cursor: pointer; font-family: var(--font-ui); min-height: 32px; }
.sealed { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip.sm { min-height: 36px; padding: 0 12px; font-size: 14px; }
.where { overflow-wrap: anywhere; }
.side { display: grid; gap: 2px; }
.editor { display: grid; gap: 12px; padding-top: 8px; border-top: 1px dashed var(--line); }
.saved-link { display: block; margin-top: 4px; font-weight: 600; }
/* The save bar stays above the iPhone home indicator. */
.bar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 20;
  display: grid; grid-template-columns: 1fr 2fr; gap: 8px;
  padding: 10px max(16px, calc(50vw - 504px)) calc(env(safe-area-inset-bottom) + 10px);
  background: color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter: blur(10px); border-top: 1px solid var(--line);
}
.bar .hint { grid-column: 1 / -1; color: var(--muted); }
.bar .next { grid-column: 1 / -1; }
@media (min-width: 900px) {
  .grid-review { grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); align-items: start; }
  .photo { position: sticky; top: 72px; }
}
</style>
