<!--
  Add from photos: pick or take photos, say whether each shows one item or many, optionally one occasion for the
  whole batch, upload. Below, every photo still waiting on the AI or on you, from this visit or an earlier one (the
  jobs live on the server, so you can leave and come back). The list polls only while the AI still has work, slows
  down while nothing changes, and pauses while the tab is hidden.
-->
<template>
  <div class="stack">
    <div class="row">
      <RouterLink to="/" class="btn btn-quiet btn-sm back" aria-label="Back to my things">‹ Back</RouterLink>
    </div>
    <h1>Add from photos</h1>

    <p v-if="route.query.saved" class="notice notice-info" role="status">
      Saved {{ route.query.saved }} {{ route.query.saved === '1' ? 'item' : 'items' }}. <RouterLink to="/">See my things</RouterLink>
    </p>

    <section class="card card-pad stack">
      <PhotoPicker :disabled="busy" @files="uploads.add" />

      <div class="field" role="radiogroup" aria-labelledby="mode-label">
        <span id="mode-label" class="label">Each photo shows</span>
        <div class="seg mode">
          <label><input v-model="mode" type="radio" value="single" :disabled="busy" /> One item</label>
          <label><input v-model="mode" type="radio" value="group" :disabled="busy" /> Many items</label>
        </div>
        <span class="muted small">{{ mode === 'single'
          ? 'One card per photo. Best for a single thing, front on.'
          : 'A shelf, stack or display: one list per photo to tick through. Slower (about 30 s) and about 3¢ a photo.' }}</span>
      </div>

      <OccasionPicker v-model="occasionId" label="All from an occasion" none-label="No occasion" :disabled="busy" />

      <UploadList :list="uploads.state.list" waiting-text="Ready to upload" @remove="uploads.remove" />

      <p v-if="error" class="notice notice-error" role="alert">
        {{ error }}
        <button v-if="unqueued.length" type="button" class="btn btn-quiet btn-sm" :disabled="busy" @click="queue">Try again</button>
      </p>

      <button type="button" class="btn btn-primary btn-block" :disabled="busy || !toSend" @click="start">
        {{ busy ? 'Uploading…' : toSend ? `Upload and read ${toSend} ${toSend === 1 ? 'photo' : 'photos'}` : 'Choose photos first' }}
      </button>
    </section>

    <section class="stack" aria-labelledby="jobs-title">
      <div class="row">
        <h2 id="jobs-title">Waiting for you</h2>
        <span class="spacer" />
        <span v-if="polling" class="muted small" aria-live="polite">Checking…</span>
      </div>
      <p v-if="loadError" class="notice notice-error" role="alert">
        {{ loadError }} <button class="btn btn-quiet btn-sm" @click="refresh">Try again</button>
      </p>
      <p v-else-if="loaded && !jobs.length" class="muted">Nothing waiting. Photos you upload show up here until you save or discard them.</p>

      <ul class="jobs">
        <li v-for="j in jobs" :key="j.id" class="job card" :class="j.status">
          <img v-if="urlFor(j)" :src="urlFor(j)" alt="" class="thumb" @error="dropUrl(j)" />
          <span v-else class="thumb blank" aria-hidden="true">IMG</span>
          <div class="body">
            <p class="what">
              <span v-if="j.mode === 'group'" class="tag">Many items</span>
              <span v-if="j.occasion_id && occasionName(j.occasion_id)" class="tag">{{ occasionName(j.occasion_id) }}</span>
            </p>
            <p class="status small" :class="{ err: j.status === 'failed' }">
              <span v-if="j.status === 'queued' || j.status === 'processing'" class="dot" aria-hidden="true" />
              {{ statusText(j) }}
            </p>
            <div class="acts">
              <RouterLink v-if="j.status === 'needs_review'" :to="`/intake/${j.id}`" class="btn btn-primary btn-sm">Review</RouterLink>
              <template v-if="j.status === 'failed'">
                <button type="button" class="btn btn-soft btn-sm" :disabled="acting === j.id" @click="retry(j)">Try again</button>
                <RouterLink :to="`/intake/${j.id}`" class="btn btn-soft btn-sm">Add by hand</RouterLink>
              </template>
              <button v-if="j.status !== 'processing'" type="button" class="btn btn-danger-quiet btn-sm" :disabled="acting === j.id"
                @click="toDiscard = j">Discard</button>
            </div>
            <p v-if="actionError[j.id]" class="field-error" role="alert">{{ actionError[j.id] }}</p>
          </div>
        </li>
      </ul>
    </section>

    <ConfirmSheet :open="!!toDiscard" title="Discard this photo?" confirm-label="Discard" :busy="!!acting" :error="discardError"
      @cancel="toDiscard = null; discardError = ''" @confirm="discard">
      The photo and anything the AI found in it will be deleted. Nothing is saved to your things.
    </ConfirmSheet>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import ConfirmSheet from '../components/ConfirmSheet.vue'
import OccasionPicker from '../components/OccasionPicker.vue'
import PhotoPicker from '../components/PhotoPicker.vue'
import UploadList from '../components/UploadList.vue'
import { api } from '../lib/backend'
import { hasPending, jobsKey, nextDelay, statusText } from '../lib/intake'
import { forgetDraft } from '../lib/intakeDrafts'
import { loadOccasions, occasionName } from '../lib/occasions'
import { useUploads } from '../lib/uploads'

const route = useRoute()
const uploads = useUploads()
const mode = ref('single')
const occasionId = ref('')
const busy = ref(false)
const error = ref('')

// Photos uploaded but not yet in a job (the job request failed): "Try again" sends them again.
const unqueued = ref([])
const toSend = computed(() => uploads.state.list.filter((e) => e.status !== 'done').length + unqueued.value.length)

async function start() {
  error.value = ''
  busy.value = true
  const failed = await uploads.run(null, (photo) => unqueued.value.push(photo.id))
  if (failed) error.value = `${failed} ${failed === 1 ? 'photo' : 'photos'} didn't upload. Fix or remove ${failed === 1 ? 'it' : 'them'}, then try again.`
  await queue()
  busy.value = false
}

async function queue() {
  if (!unqueued.value.length) return
  busy.value = true
  try {
    const created = await api.createIntakeJobs(unqueued.value, mode.value, occasionId.value || null)
    unqueued.value = []
    uploads.clearDone()
    merge(created)
    schedule(true)
  } catch (e) {
    error.value = `${e.message} Your photos are uploaded; try again to send them to the AI.`
  } finally {
    busy.value = false
  }
}

// --- the list of open jobs, polled politely ---

const jobs = ref([])
const loaded = ref(false)
const loadError = ref('')
const polling = ref(false)
let timer = null
let delay = 0
let stopped = false

// Signed URLs change on every poll; keep the first one for each photo so thumbnails don't reload.
const urls = reactive({})
const urlFor = (j) => (j.photo ? urls[j.photo.id] : null)
const dropUrl = (j) => { if (j.photo) urls[j.photo.id] = null }
function keepUrls(list) {
  for (const j of list) if (j.photo && !(j.photo.id in urls)) urls[j.photo.id] = j.photo.url
}

function merge(fresh) {
  keepUrls(fresh)
  const byId = new Map(jobs.value.map((j) => [j.id, j]))
  for (const j of fresh) byId.set(j.id, j)
  jobs.value = [...byId.values()].filter((j) => !['done', 'discarded'].includes(j.status))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

async function refresh() {
  const before = jobsKey(jobs.value)
  polling.value = true
  try {
    const list = await api.listIntakeJobs({ open: true, limit: 100 })
    keepUrls(list)
    jobs.value = list
    loadError.value = ''
    loaded.value = true
  } catch (e) {
    loadError.value = `Could not load your photos. ${e.message}`
  } finally {
    polling.value = false
  }
  return jobsKey(jobs.value) !== before
}

function schedule(changed) {
  clearTimeout(timer)
  timer = null
  if (stopped || document.hidden || !hasPending(jobs.value)) return
  delay = nextDelay(delay, changed)
  timer = setTimeout(async () => schedule(await refresh()), delay)
}

function onVisible() {
  if (!document.hidden) refresh().then(() => schedule(true))
  else clearTimeout(timer)
}

onMounted(async () => {
  loadOccasions()
  await refresh()
  schedule(true)
  document.addEventListener('visibilitychange', onVisible)
})
onBeforeUnmount(() => {
  stopped = true
  clearTimeout(timer)
  document.removeEventListener('visibilitychange', onVisible)
})

// --- per-job actions ---

const acting = ref(null)
const actionError = reactive({})
const toDiscard = ref(null)
const discardError = ref('')

async function retry(j) {
  acting.value = j.id
  delete actionError[j.id]
  try {
    merge([await api.retryIntakeJob(j.id)])
    schedule(true)
  } catch (e) {
    actionError[j.id] = e.message
  } finally {
    acting.value = null
  }
}

async function discard() {
  const j = toDiscard.value
  acting.value = j.id
  discardError.value = ''
  try {
    await api.discardIntakeJob(j.id)
    forgetDraft(j.id)
    jobs.value = jobs.value.filter((x) => x.id !== j.id)
    toDiscard.value = null
  } catch (e) {
    discardError.value = e.message
  } finally {
    acting.value = null
  }
}
</script>

<style scoped>
.back { margin-left: -12px; }
.mode { width: 100%; }
.jobs { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.job { display: flex; gap: 12px; padding: 10px; align-items: flex-start; }
.job.needs_review { border-color: var(--accent); }
.job.failed { border-color: var(--danger); }
.thumb { width: 64px; height: 64px; flex: none; border-radius: 8px; object-fit: cover; background: var(--surface-2); }
.blank { display: grid; place-items: center; font-size: 11px; color: var(--faint); }
.body { flex: 1; min-width: 0; display: grid; gap: 6px; }
.what { display: flex; flex-wrap: wrap; gap: 6px; }
.what:empty { display: none; }
.tag { padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: 0.8rem; }
.status { color: var(--text); overflow-wrap: anywhere; }
.status.err { color: var(--danger); }
.dot { display: inline-block; width: 8px; height: 8px; margin-right: 4px; border-radius: 50%; background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.3; } }
.acts { display: flex; flex-wrap: wrap; gap: 6px; }
.acts .btn-danger-quiet { margin-left: auto; }
</style>
