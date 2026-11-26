<!--
  Which film, show or book this is (S12). Searches the catalog once when it opens (TMDB for films and shows, Open
  Library for books) and again when you edit the title and search. A strong match is preselected and labelled; a weak
  one is listed with nothing chosen, so nothing is linked unless you pick it. "None of these" is always there.
  Games have no catalog yet and other categories never get here.

  With `allowShare`, a box to add the release to the shared catalog, saying what is shared and what stays private.
  v-model: {choice: a candidate's ref | 'none' | null, share, query: {title, year}, result}.
-->
<template>
  <section class="card card-pad stack catalog" aria-label="Catalog match">
    <p class="label">{{ heading }}</p>

    <p v-if="linkedWork" class="linked">
      In the shared catalog as <strong>{{ candidateLine(linkedWork) }}</strong>.
    </p>

    <template v-else-if="searchable(kind)">
      <p v-if="loading" class="muted" aria-busy="true">Searching {{ kind === 'book' ? 'Open Library' : 'TMDB' }}…</p>
      <p v-else-if="result?.status === 'unavailable'" class="notice notice-warn small">{{ result.message }}</p>
      <fieldset v-else-if="result" class="choices">
        <legend class="sr-only">Pick the matching title</legend>
        <label v-for="(c, i) in result.candidates" :key="c.ref" class="choice">
          <input v-model="choice" type="radio" :name="`work-${uid}`" :value="c.ref" />
          <span class="text">
            <span class="title">{{ candidateLine(c) }}</span>
            <span class="muted small">{{ [c.kind === 'tv' ? 'TV' : c.kind === 'movie' ? 'Film' : 'Book', c.detail, SOURCE_LABEL[c.source]].filter(Boolean).join(' · ') }}</span>
          </span>
          <span v-if="i === 0 && result.strength === 'strong'" class="tag">Best match</span>
        </label>
        <p v-if="!result.candidates.length" class="muted small">No match in the catalog.</p>
        <label class="choice">
          <input v-model="choice" type="radio" :name="`work-${uid}`" value="none" />
          <span class="text"><span class="title">None of these</span></span>
        </label>
      </fieldset>
      <p v-if="result?.strength === 'weak' && !choice" class="muted small">Not sure which one this is: pick it, or None of these. Nothing is linked until you choose.</p>

      <form class="again" @submit.prevent="search(again)">
        <label class="field">
          <span>Search for</span>
          <input v-model="again" class="input" enterkeyhint="search" maxlength="300" />
        </label>
        <button class="btn btn-soft" :disabled="loading || !again.trim()">Search</button>
      </form>
      <p v-if="result?.sources?.length" class="muted small">
        Data from
        <template v-for="(s, i) in result.sources" :key="s"><template v-if="i"> and </template>
          <a :href="s === 'tmdb' ? 'https://www.themoviedb.org' : 'https://openlibrary.org'" target="_blank" rel="noopener noreferrer">{{ SOURCE_LABEL[s] }}</a></template>.
        <RouterLink to="/about">Credits</RouterLink>
      </p>
    </template>

    <template v-if="allowShare">
      <label class="share">
        <input v-model="share" type="checkbox" />
        <span>Add this release to the shared catalog</span>
      </label>
      <p v-if="share" class="muted small">Shared with everyone: {{ SHARED_TEXT }}. {{ PRIVATE_TEXT }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../lib/backend'
import { PRIVATE_TEXT, SHARED_TEXT, SOURCE_LABEL, candidateLine, searchable } from '../lib/catalog'

const props = defineProps({
  query: { type: Object, required: true },        // {title, kind, year, isbn}
  kind: { type: String, default: null },
  linkedWork: { type: Object, default: null },
  allowShare: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const uid = Math.random().toString(36).slice(2, 8)
const loading = ref(false)
const result = ref(null)
const choice = ref(null)
const share = ref(props.allowShare)
const again = ref(props.query.title || '')
const asked = ref({ title: props.query.title, year: props.query.year })

const heading = computed(() => ({
  movie: 'Which film is this?', tv: 'Which show is this?', screen: 'Which film or show is this?', book: 'Which book is this?',
  game: 'Shared catalog',
}[props.kind] || 'Catalog'))

async function search(title) {
  loading.value = true
  choice.value = null
  // A typed search replaces the title; the AI's year hint only goes with the AI's own title.
  const q = title === props.query.title ? props.query : { ...props.query, title, year: null, isbn: null }
  asked.value = { title: q.title, year: q.year }
  try {
    result.value = await api.searchCatalog(q)
  } catch (e) {
    result.value = { status: 'unavailable', candidates: [], message: e.message }
  } finally {
    loading.value = false
  }
  if (result.value.strength === 'strong') choice.value = result.value.candidates[0].ref
}

onMounted(() => {
  if (!props.linkedWork && searchable(props.kind) && (props.query.title || props.query.isbn)) search(props.query.title)
})

watch([choice, share, result, asked], () => {
  emit('update:modelValue', { choice: choice.value, share: share.value, query: asked.value, result: result.value })
}, { immediate: true })
</script>

<style scoped>
.catalog { gap: 10px; }
.choices { border: 0; margin: 0; padding: 0; display: grid; gap: 6px; min-width: 0; }
.choice {
  display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; min-height: var(--tap);
  padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; cursor: pointer;
}
.choice:has(input:checked) { border-color: var(--accent); background: var(--accent-soft); }
.choice input { width: 20px; height: 20px; margin: 0; }
.text { display: grid; min-width: 0; }
.title { font-weight: 600; overflow-wrap: anywhere; }
.tag { font-size: 0.75rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--accent); color: var(--on-accent, #fff); white-space: nowrap; }
.again { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; }
.share { display: flex; gap: 10px; align-items: center; min-height: var(--tap); font-weight: 600; cursor: pointer; }
.share input { width: 20px; height: 20px; margin: 0; }
.linked { overflow-wrap: anywhere; }
</style>
