<!--
  Add by barcode: scan with the camera, type the number, or pick a photo of the barcode. Every code passes the
  check digit here and again on the server before anything is looked up.

  Found: the confirmation card appears at once, with no AI call. It is made of the S10 card's parts (the one-tap
  questions, the item form, the occasion picker) and the edition is always a question, never pre-filled. Saving makes
  my private item linked to the shared release; the card then clears for the next scan.
  Not found, or the catalog can't be asked right now: photograph the box (AI intake) or add it by hand, keeping the
  barcode either way.
  S12: a film, show or book release shows its work. A release with no work yet searches the catalog (CatalogMatch)
  and, if you pick a match, saving links it; the first link wins and nobody can change it afterwards.
-->
<template>
  <div class="stack">
    <div class="row">
      <RouterLink to="/" class="btn btn-quiet btn-sm back" aria-label="Back to my things">‹ Back</RouterLink>
    </div>
    <h1>{{ phase === 'found' ? 'Check the card' : 'Scan a barcode' }}</h1>

    <p v-if="saved" class="notice notice-info" role="status">
      Saved <RouterLink :to="`/items/${saved.id}`">{{ saved.name }}</RouterLink>. Scan the next one.
      <span v-if="saved.note" class="block">{{ saved.note }}</span>
    </p>

    <!-- finding the code -->
    <section v-if="phase !== 'found'" class="card card-pad stack">
      <BarcodeScanner :disabled="phase === 'looking'" @code="lookup" />

      <form class="typed" @submit.prevent="lookup(typed)">
        <label class="field">
          <span>Or type the number under the barcode</span>
          <input v-model="typed" class="input" inputmode="numeric" autocomplete="off" enterkeyhint="search"
            maxlength="20" placeholder="e.g. 883929704736" :disabled="phase === 'looking'" aria-describedby="code-error" />
        </label>
        <button class="btn btn-soft" :disabled="phase === 'looking' || !typed.trim()">Look up</button>
      </form>

      <label class="btn btn-soft btn-block photo">
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m4 16 5-5 4 4 3-3 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
        {{ reading ? 'Reading the photo…' : 'Pick a photo of the barcode' }}
        <input class="sr-only" type="file" accept="image/*" :disabled="phase === 'looking' || reading" @change="fromPhoto" />
      </label>

      <p v-if="codeError" id="code-error" class="notice notice-error" role="alert">{{ codeError }}</p>
      <p v-if="phase === 'looking'" class="muted" aria-busy="true">Looking up {{ shown }}…</p>
    </section>

    <!-- nothing in the catalog (or it can't be asked) -->
    <section v-if="phase === 'miss'" class="card card-pad stack" aria-live="polite">
      <p><strong>{{ missText(result) }}</strong> Barcode {{ shown }} is kept either way.</p>
      <div class="two">
        <RouterLink :to="{ path: '/intake', query: { barcode: result.barcode } }" class="btn btn-primary">Photograph the box</RouterLink>
        <RouterLink :to="{ path: '/items/new', query: { barcode: result.barcode } }" class="btn btn-soft">Add by hand</RouterLink>
      </div>
      <p class="muted small">The AI reads the box and fills in the card for you to check.</p>
    </section>

    <!-- found: the confirmation card -->
    <template v-if="phase === 'found'">
      <section class="card card-pad release">
        <p class="muted small">{{ result.source === 'upcitemdb' ? 'Found by barcode and added to the shared catalog' : 'Found by barcode in the shared catalog' }}</p>
        <p class="title">{{ result.release.title }}</p>
        <p class="muted small">Barcode {{ shown }}<span v-if="result.release.publisher"> · {{ result.release.publisher }}</span></p>
      </section>

      <p v-if="!ready" class="muted" aria-busy="true">Preparing the card…</p>
      <template v-else>
        <FollowUps :questions="questions" @answer="onAnswer" />
        <fieldset class="card card-pad stack" :disabled="busy">
          <ItemForm :draft="draft" :errors="errors" :flags="flags" @update:draft="onDraft" @fields="fields = $event" />
          <OccasionPicker :model-value="draft.occasion_id" @update:model-value="onDraft({ ...draft, occasion_id: $event })" />
        </fieldset>
        <CatalogMatch v-if="searchable(kind) || result.release.work" v-model="catalog" :query="query" :kind="kind"
          :linked-work="result.release.work" />
        <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
        <div class="two">
          <button type="button" class="btn btn-soft" :disabled="busy" @click="reset">Scan another</button>
          <button type="button" class="btn btn-primary" :disabled="busy || !canSave" @click="save">{{ busy ? 'Saving…' : 'Save item' }}</button>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import BarcodeScanner from '../components/BarcodeScanner.vue'
import CatalogMatch from '../components/CatalogMatch.vue'
import FollowUps from '../components/FollowUps.vue'
import ItemForm from '../components/ItemForm.vue'
import OccasionPicker from '../components/OccasionPicker.vue'
import { api } from '../lib/backend'
import { categoryForKind, displayBarcode, editionQuestion, lookupToDraft, missText, parseBarcode } from '../lib/barcode'
import { candidateLine, isbnOf, searchable } from '../lib/catalog'
import { categoryFields, cleanDraft, loadCategories } from '../lib/categories'
import { answer, clearFlags, confirmItem, followUps } from '../lib/intake'
import { loadOccasions } from '../lib/occasions'
import { decodePhoto } from '../lib/scanner'

const phase = ref('scan') // scan | looking | found | miss
const typed = ref('')
const codeError = ref('')
const reading = ref(false)
const result = ref(null)
const saved = ref(null)
const shown = computed(() => (result.value ? displayBarcode(result.value.barcode) : typed.value.trim()))

loadOccasions()

async function lookup(input) {
  codeError.value = ''
  const parsed = typeof input === 'string' ? parseBarcode(input) : input
  if (parsed.error) {
    codeError.value = parsed.error
    return
  }
  typed.value = displayBarcode(parsed.code)
  result.value = null
  phase.value = 'looking'
  try {
    const r = await api.lookupBarcode(parsed.code)
    result.value = r
    if (r.status === 'found') await openCard(r)
    else phase.value = 'miss'
  } catch (e) {
    phase.value = 'scan'
    codeError.value = e.message
  }
}

async function fromPhoto(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  codeError.value = ''
  reading.value = true
  try {
    const hit = await decodePhoto(file)
    if (hit) await lookup(hit)
    else codeError.value = "No barcode found in that photo. Try a closer, sharper one, or type the number."
  } catch {
    codeError.value = "That photo couldn't be opened here. Try a JPEG or PNG, or type the number."
  } finally {
    reading.value = false
  }
}

// --- the card ---

const draft = ref(null)
const flags = ref({})
const fields = ref([])
const ready = ref(false)
const catalog = ref(null)
// The listing's kind -> the catalog's: a disc listing may be a film or a show.
const kind = computed(() => ({ movie: 'screen', book: 'book', game: 'game' }[result.value?.hints?.kind] || null))
const query = computed(() => ({ title: result.value?.release?.title || '', kind: kind.value, year: null,
  isbn: kind.value === 'book' ? isbnOf(result.value?.barcode) : null }))

async function openCard(r) {
  saved.value = null
  ready.value = false
  phase.value = 'found'
  const cats = await loadCategories().catch(() => null)
  const categoryId = categoryForKind(r.hints?.kind, cats ? Object.values(cats.byId) : [])
  fields.value = categoryId ? await categoryFields(categoryId).catch(() => []) : []
  ;({ draft: draft.value, flags: flags.value } = lookupToDraft(r, fields.value, { categoryId }))
  ready.value = true
}

const questions = computed(() => {
  if (!draft.value) return []
  const ed = editionQuestion(draft.value, fields.value, result.value?.hints)
  return [...(ed ? [ed] : []), ...followUps(draft.value, fields.value)]
})
const canSave = computed(() => draft.value && draft.value.name.trim() && draft.value.category_id)

function onDraft(next) {
  flags.value = clearFlags(draft.value, next, flags.value)
  draft.value = next
}
const onAnswer = (key, value) => onDraft(answer(draft.value, key, value))

const busy = ref(false)
const error = ref('')
const errors = ref({})

async function save() {
  if (!canSave.value || busy.value) return
  busy.value = true
  error.value = ''
  errors.value = {}
  try {
    const note = await linkWork()
    const item = await api.createItem(confirmItem(await cleanDraft(draft.value)))
    saved.value = { id: item.id, name: item.name, note }
    reset({ keepSaved: true })
  } catch (e) {
    error.value = e.message
    errors.value = e.fields || {}
  } finally {
    busy.value = false
  }
}

/** Links the release to the picked work, if it has none. A failure doesn't stop the save: it's said after. */
async function linkWork() {
  const ref_ = catalog.value?.choice
  const release = result.value.release
  if (release.work || !ref_ || ref_ === 'none') return ''
  try {
    const r = await api.linkReleaseWork(release.id, ref_)
    return r.linked ? '' : `Someone already linked this release to ${candidateLine(r.work)}; it stays that way.`
  } catch (e) {
    return `Not linked to the catalog: ${e.message}`
  }
}

function reset({ keepSaved = false } = {}) {
  if (!keepSaved) saved.value = null
  phase.value = 'scan'
  result.value = null
  draft.value = null
  catalog.value = null
  typed.value = ''
  codeError.value = ''
  error.value = ''
}
</script>

<style scoped>
.back { margin-left: -12px; }
fieldset { border: 1px solid var(--line); margin: 0; min-width: 0; }
.typed { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; }
.photo { position: relative; }
.photo:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.release { display: grid; gap: 4px; }
.release .title { font-weight: 600; font-size: 1.05rem; overflow-wrap: anywhere; }
.block { display: block; margin-top: 4px; }
</style>
