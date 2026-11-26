<template>
  <form class="stack" @submit.prevent="save">
    <div class="row">
      <RouterLink to="/" class="btn btn-quiet btn-sm back" aria-label="Back to my things">‹ Back</RouterLink>
    </div>
    <h1>Add an item</h1>
    <p v-if="barcode" class="notice notice-info small">Barcode {{ displayBarcode(barcode) }} is saved with this item.</p>

    <p v-if="loadError" class="notice notice-error" role="alert">{{ loadError }}</p>

    <fieldset class="card card-pad stack" :disabled="!!created">
      <ItemForm v-model:draft="draft" :errors="fieldErrors" />
    </fieldset>

    <section class="card card-pad stack">
      <div class="row">
        <h2>Photos</h2>
        <span class="muted small">optional</span>
      </div>
      <PhotoPicker :disabled="uploads.busy()" @files="uploads.add" />
      <UploadList :list="uploads.state.list" @remove="uploads.remove" />
    </section>

    <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>

    <template v-if="created && failed">
      <p class="notice notice-warn">
        "{{ created.name }}" is saved, but {{ failed }} {{ failed === 1 ? 'photo' : 'photos' }} didn't upload.
        Try again, or open the item and add them later.
      </p>
      <div class="actions">
        <RouterLink :to="`/items/${created.id}`" class="btn btn-soft">Open item</RouterLink>
        <button type="button" class="btn btn-primary" :disabled="uploads.busy()" @click="uploadPhotos">Retry upload</button>
      </div>
    </template>
    <button v-else class="btn btn-primary btn-block" :disabled="busy || !canSave">
      {{ busy ? (created ? 'Uploading photos…' : 'Saving…') : 'Save item' }}
    </button>
  </form>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ItemForm from '../components/ItemForm.vue'
import PhotoPicker from '../components/PhotoPicker.vue'
import UploadList from '../components/UploadList.vue'
import { api } from '../lib/backend'
import { displayBarcode, parseBarcode } from '../lib/barcode'
import { cleanDraft, loadCategories } from '../lib/categories'
import { createBody, emptyDraft } from '../lib/item'
import { forgetCover } from '../lib/photos'
import { useUploads } from '../lib/uploads'

const router = useRouter()
// From a barcode the catalog didn't know (/scan): kept on the item until S12 makes shared releases from it.
const barcode = parseBarcode(useRoute().query.barcode || '').code || ''
const draft = ref({ ...emptyDraft(), attributes: barcode ? { barcode } : {} })
const uploads = useUploads()
const busy = ref(false)
const error = ref('')
const fieldErrors = ref({})
const loadError = ref('')
const created = ref(null)
const failed = ref(0)

onMounted(() => loadCategories().catch((e) => { loadError.value = `Could not load categories. ${e.message}` }))

const canSave = computed(() => draft.value.name.trim() && draft.value.category_id)

async function save() {
  if (!canSave.value) return
  error.value = ''
  fieldErrors.value = {}
  busy.value = true
  try {
    // The item first: photos are uploaded to an item, so it has to exist.
    created.value = await api.createItem(createBody(await cleanDraft(draft.value)))
  } catch (e) {
    error.value = e.message
    fieldErrors.value = e.fields || {}
    busy.value = false
    return
  }
  await uploadPhotos()
}

async function uploadPhotos() {
  busy.value = true
  failed.value = await uploads.run(created.value.id)
  forgetCover(created.value.id)
  busy.value = false
  if (!failed.value) router.replace(`/items/${created.value.id}`)
}
</script>

<style scoped>
.back { margin-left: -12px; }
fieldset { border: 1px solid var(--line); margin: 0; min-width: 0; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
</style>
