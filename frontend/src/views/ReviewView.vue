<!--
  Review one intake job: the single-item card or the group grid. After saving or discarding, goes to the next photo
  waiting for review, or back to the intake list. A job still with the AI shows progress until it's ready.
-->
<template>
  <div class="stack">
    <div class="row">
      <RouterLink to="/intake" class="btn btn-quiet btn-sm back" aria-label="Back to photos">‹ Photos</RouterLink>
      <span class="spacer" />
      <span v-if="waiting > 0" class="muted small">{{ waiting }} more to review</span>
    </div>
    <h1>{{ job?.mode === 'group' ? 'Check the shelf' : 'Check the card' }}</h1>

    <p v-if="error" class="notice notice-error" role="alert">{{ error }} <button class="btn btn-quiet btn-sm" @click="load">Try again</button></p>
    <p v-else-if="!job" class="muted" aria-busy="true">Loading…</p>

    <template v-else-if="job.status === 'queued' || job.status === 'processing'">
      <p class="notice notice-info" role="status">
        {{ statusText(job) }}. This page updates by itself{{ job.mode === 'group' ? '; a shelf takes about half a minute' : '' }}.
      </p>
    </template>

    <section v-else-if="job.status === 'done'" class="notice notice-info" role="status">
      Already saved:
      <RouterLink v-for="it in job.items" :key="it.id" :to="`/items/${it.id}`" class="saved-link">{{ it.name }}</RouterLink>
    </section>
    <p v-else-if="job.status === 'discarded'" class="notice notice-info" role="status">This photo was discarded.</p>

    <template v-else>
      <IntakeGrid v-if="job.mode === 'group'" :key="job.id" :job="job" @finished="next" />
      <IntakeCard v-else :key="job.id" :job="job" @finished="next" />
    </template>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import IntakeCard from '../components/IntakeCard.vue'
import IntakeGrid from '../components/IntakeGrid.vue'
import { api } from '../lib/backend'
import { loadCategories } from '../lib/categories'
import { nextDelay, statusText } from '../lib/intake'
import { loadOccasions } from '../lib/occasions'
import { forgetCover } from '../lib/photos'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const job = ref(null)
const error = ref('')
const waiting = ref(0)
let timer = null
let delay = 0
let savedSoFar = 0

async function load() {
  error.value = ''
  clearTimeout(timer)
  try {
    const [j] = await Promise.all([api.getIntakeJob(props.id), loadCategories(), loadOccasions()])
    const changed = !job.value || job.value.status !== j.status || job.value.attempts !== j.attempts
    job.value = j
    if (j.status === 'queued' || j.status === 'processing') {
      delay = nextDelay(delay, changed)
      timer = setTimeout(load, delay)
    }
    countWaiting()
  } catch (e) {
    error.value = e.status === 404 ? 'No such photo to review.' : `Could not load this photo. ${e.message}`
  }
}

async function countWaiting() {
  try {
    const open = await api.listIntakeJobs({ open: true, limit: 100 })
    waiting.value = open.filter((j) => j.status === 'needs_review' && j.id !== props.id).length
    return open
  } catch {
    return []
  }
}

async function next({ saved, items = [] }) {
  savedSoFar += saved
  for (const it of items) forgetCover(it.id)
  const open = await countWaiting()
  const following = open.filter((j) => j.status === 'needs_review' && j.id !== props.id).at(-1) // oldest first
  if (following) router.replace(`/intake/${following.id}`)
  else router.replace({ path: '/intake', query: savedSoFar ? { saved: String(savedSoFar) } : {} })
}

watch(() => props.id, () => { job.value = null; delay = 0; load() }, { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.back { margin-left: -12px; }
.saved-link { display: block; margin-top: 4px; font-weight: 600; }
</style>
