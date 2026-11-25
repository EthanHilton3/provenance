<template>
  <div class="stack">
    <div class="row">
      <RouterLink to="/" class="btn btn-quiet btn-sm back" aria-label="Back to my things">‹ My things</RouterLink>
    </div>

    <div v-if="loading" class="muted" aria-busy="true">Loading…</div>

    <section v-else-if="notFound" class="card card-pad stack">
      <h1>Item not found</h1>
      <p class="muted">It may have been deleted on another device.</p>
      <RouterLink to="/" class="btn btn-soft">Back to my things</RouterLink>
    </section>

    <p v-else-if="error" class="notice notice-error" role="alert">
      {{ error }} <button class="btn btn-quiet btn-sm" @click="load">Try again</button>
    </p>

    <!-- Reading -->
    <template v-else-if="item && !editing">
      <p v-if="notice" class="notice notice-info" role="status">{{ notice }}</p>

      <header class="title">
        <p class="muted small">{{ categoryPath(item.category_id) }}</p>
        <h1>{{ item.name }}</h1>
      </header>

      <section class="card card-pad">
        <CategoryFields :category-id="item.category_id" :model-value="item.attributes || {}" @fields="learnLabels" />
        <dl class="rows">
          <div v-for="r in basics" :key="r.label" class="r">
            <dt>{{ r.label }}</dt>
            <dd>{{ r.value }}</dd>
          </div>
        </dl>
        <p v-if="!basics.length && !Object.keys(item.attributes || {}).length" class="muted small">
          No details yet. Tap Edit to add some.
        </p>
      </section>

      <section class="stack">
        <h2>Photos <span v-if="photos.length" class="muted small">{{ photos.length }}</span></h2>
        <p v-if="photoError" class="notice notice-error small">{{ photoError }}</p>
        <ul v-if="photos.length" class="photos">
          <li v-for="p in photos" :key="p.id">
            <button class="ph" :aria-label="`Open photo ${photos.indexOf(p) + 1}`" @click="viewing = p">
              <img v-if="p.url" :src="p.url" alt="" loading="lazy" />
              <span v-else class="missing small">Missing</span>
            </button>
          </li>
        </ul>
        <p v-else-if="!uploads.state.list.length" class="muted small">No photos yet.</p>
        <PhotoPicker :disabled="uploads.busy()" @files="addPhotos" />
        <UploadList :list="uploads.state.list" @remove="uploads.remove" />
      </section>

      <div class="actions">
        <button class="btn btn-danger-quiet" @click="askDelete = true">Delete</button>
        <button class="btn btn-primary" @click="startEdit">Edit</button>
      </div>
    </template>

    <!-- Editing -->
    <form v-else-if="item && editing" class="stack" @submit.prevent="save()">
      <h1>Edit</h1>
      <div class="card card-pad">
        <ItemForm v-model:draft="draft" :errors="fieldErrors" />
      </div>

      <ConflictPanel v-if="conflict" :base="base" :current="conflict" :draft="draft" :label-for="(k) => labels[k]"
        :busy="saving" @reload="useTheirs" @overwrite="save(conflict)" />
      <p v-if="saveError" class="notice notice-error" role="alert">{{ saveError }}</p>

      <div v-if="!conflict" class="actions sticky">
        <button type="button" class="btn btn-soft" :disabled="saving" @click="cancelEdit">Cancel</button>
        <button class="btn btn-primary" :disabled="saving || !draft.name.trim() || !draft.category_id">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </form>

    <ConfirmSheet :open="askDelete" :title="`Delete “${item?.name}”?`" :busy="deleting" :error="deleteError"
      @cancel="askDelete = false; deleteError = ''" @confirm="remove">
      The item and its {{ photos.length }} {{ photos.length === 1 ? 'photo' : 'photos' }} will be gone for good.
    </ConfirmSheet>

    <ConfirmSheet :open="!!photoToDelete" title="Delete this photo?" :busy="deleting" :error="deleteError"
      @cancel="photoToDelete = null; deleteError = ''" @confirm="removePhoto">
      It can't be brought back.
    </ConfirmSheet>

    <Teleport to="body">
      <div v-if="viewing" class="viewer" role="dialog" aria-modal="true" aria-label="Photo" @click.self="viewing = null"
        @keydown.esc="viewing = null">
        <img :src="viewing.url" alt="" />
        <div class="viewer-bar">
          <button class="btn btn-soft" @click="photoToDelete = viewing; viewing = null">Delete photo</button>
          <button ref="closeBtn" class="btn btn-primary" @click="viewing = null">Close</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import CategoryFields from '../components/CategoryFields.vue'
import ConfirmSheet from '../components/ConfirmSheet.vue'
import ConflictPanel from '../components/ConflictPanel.vue'
import ItemForm from '../components/ItemForm.vue'
import PhotoPicker from '../components/PhotoPicker.vue'
import UploadList from '../components/UploadList.vue'
import { ConflictError } from '../lib/api'
import { api } from '../lib/backend'
import { categoryFields, categoryPath, cleanDraft, loadCategories } from '../lib/categories'
import { buildPatch, display, draftFrom } from '../lib/item'
import { forgetCover, setCover } from '../lib/photos'
import { useUploads } from '../lib/uploads'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()

const item = ref(null)
const photos = ref([])
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const notice = ref('')
const photoError = ref('')

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const [it] = await Promise.all([api.getItem(props.id), loadCategories()])
    item.value = it
    await loadPhotos()
  } catch (e) {
    if (e.status === 404) notFound.value = true
    else error.value = e.message
  } finally {
    loading.value = false
  }
}
async function loadPhotos() {
  photoError.value = ''
  try {
    photos.value = await api.listPhotos(props.id)
    setCover(props.id, photos.value.find((p) => p.url)?.url ?? null)
  } catch (e) {
    photoError.value = `Could not load photos. ${e.message}`
  }
}
watch(() => props.id, load, { immediate: true })

const basics = computed(() => {
  const it = item.value
  if (!it) return []
  const rows = [
    ['Franchise / series', 'franchise'], ['Brand / maker', 'brand'], ['Signed by', 'signed_by'],
    ['Condition', 'condition_grade'], ['Sealed', 'sealed'], ['Acquired', 'acquired_on'], ['Where from', 'source'], ['Notes', 'notes'],
  ]
  return rows
    .filter(([, k]) => (k === 'sealed' ? it.sealed : it[k]))
    .map(([label, k]) => ({ label, value: display(k, it[k]) }))
})

// Field labels for the conflict panel, from every category this item has been in during the edit.
const labels = ref({})
function learnLabels(fields) {
  for (const f of fields) labels.value[f.key] = f.label
}
const learnCategory = (id) => categoryFields(id).then(learnLabels).catch(() => {})

// ---- Editing, with optimistic locking: `base` is the item as loaded, and its version goes with the save.
const editing = ref(false)
const base = ref(null)
const draft = ref(null)
const saving = ref(false)
const saveError = ref('')
const fieldErrors = ref({})
const conflict = ref(null) // the current row after a 409

function startEdit() {
  notice.value = ''
  base.value = item.value
  draft.value = draftFrom(item.value)
  conflict.value = null
  saveError.value = ''
  fieldErrors.value = {}
  editing.value = true
  learnCategory(item.value.category_id)
}
function cancelEdit() {
  editing.value = false
  conflict.value = null
}

/** Saves the draft. With `onto` (the current row after a 409) only your changed fields go, on their version. */
async function save(onto) {
  saveError.value = ''
  fieldErrors.value = {}
  const patch = buildPatch(base.value, await cleanDraft(draft.value), onto || base.value)
  if (!patch) {
    if (onto) item.value = onto
    editing.value = false
    conflict.value = null
    return
  }
  saving.value = true
  try {
    item.value = await api.updateItem(props.id, patch)
    editing.value = false
    conflict.value = null
    notice.value = 'Saved.'
    window.scrollTo({ top: 0 })
  } catch (e) {
    if (e instanceof ConflictError) {
      // Someone saved after we loaded (or, on "save on top", saved again in between): show what they changed.
      // `base` stays the row you loaded, so "your changes" never include fields only they touched.
      conflict.value = e.current
      learnCategory(e.current.category_id)
      // The panel sits under a long form: bring it on screen, or on a phone the Save tap looks like it did nothing.
      await nextTick()
      document.querySelector('.conflict')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else if (e.status === 404) {
      notFound.value = true
      editing.value = false
    } else {
      saveError.value = e.message
      fieldErrors.value = e.fields || {}
    }
  } finally {
    saving.value = false
  }
}

function useTheirs() {
  item.value = conflict.value
  conflict.value = null
  editing.value = false
  notice.value = 'Showing the latest saved version. Your edits were discarded.'
  window.scrollTo({ top: 0 })
}

// ---- Photos
const uploads = useUploads()
async function addPhotos(files) {
  uploads.add(files)
  await uploads.run(props.id)
  uploads.clearDone()
  await loadPhotos()
}

const viewing = ref(null)
const closeBtn = ref(null)
watch(viewing, async (v) => { if (v) { await nextTick(); closeBtn.value?.focus() } })

const photoToDelete = ref(null)
const askDelete = ref(false)
const deleting = ref(false)
const deleteError = ref('')

async function removePhoto() {
  deleting.value = true
  deleteError.value = ''
  try {
    await api.deletePhoto(photoToDelete.value.id)
    photoToDelete.value = null
    await loadPhotos()
  } catch (e) {
    deleteError.value = e.message
  } finally {
    deleting.value = false
  }
}

async function remove() {
  deleting.value = true
  deleteError.value = ''
  try {
    await api.deleteItem(props.id)
    forgetCover(props.id)
    askDelete.value = false
    router.replace('/')
  } catch (e) {
    if (e.status === 404) return router.replace('/')
    deleteError.value = e.message
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.back { margin-left: -12px; }
.title { display: grid; gap: 4px; }
.title h1 { overflow-wrap: anywhere; }
.rows { margin: 0; display: grid; }
.r { display: grid; grid-template-columns: minmax(110px, 38%) 1fr; gap: 12px; padding: 10px 0; border-top: 1px solid var(--line); }
dt { color: var(--muted); }
dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.card > .rows:first-child .r:first-child { border-top: 0; }
h2 { display: flex; gap: 8px; align-items: baseline; }

.photos { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.ph { display: block; width: 100%; aspect-ratio: 1; padding: 0; border: 0; border-radius: 10px; overflow: hidden; background: var(--surface-2); cursor: zoom-in; }
.ph img { width: 100%; height: 100%; object-fit: cover; }
.missing { display: grid; place-items: center; height: 100%; color: var(--faint); }

.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.sticky {
  position: sticky; bottom: 0; padding: 12px 0 calc(env(safe-area-inset-bottom) + 12px);
  background: linear-gradient(to top, var(--bg) 70%, transparent);
}

.viewer {
  position: fixed; inset: 0; z-index: 60; display: grid; grid-template-rows: 1fr auto; gap: 12px;
  padding: calc(env(safe-area-inset-top) + 12px) 12px calc(env(safe-area-inset-bottom) + 12px);
  background: rgb(0 0 0 / 0.92);
}
.viewer img { width: 100%; height: 100%; object-fit: contain; min-height: 0; }
.viewer-bar { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; max-width: 520px; width: 100%; margin: 0 auto; }
</style>
