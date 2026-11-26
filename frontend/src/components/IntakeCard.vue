<!--
  The confirmation card for one photo of one item: the photo beside the AI's proposal, every value editable, unsure
  values marked, the follow-up questions on top. Save creates the item; Discard throws the card and photo away.
  A failed job opens the same card, blank, so the item can be added by hand with its photo.
  Unsaved edits are kept on this device until you save or discard (lib/intakeDrafts.js).
-->
<template>
  <div class="review">
    <IntakePhoto class="photo" :url="job.photo?.url || ''" />

    <div class="stack">
      <p v-if="job.status === 'failed'" class="notice notice-warn">
        The AI couldn't read this photo<span v-if="job.error">: {{ job.error.replace(/\.\s*$/, '') }}</span>. Fill in what it is and save it with its photo.
      </p>
      <p v-else-if="card" class="muted small">{{ sureness }}</p>
      <p v-if="card && card.item_count > 1" class="notice notice-warn small">
        The AI sees {{ card.item_count }} things in this photo. Saving makes one item; for a shelf, use "Many items".
      </p>

      <p v-if="!ready" class="muted" aria-busy="true">Preparing the card…</p>
      <template v-else>
        <FollowUps :ai-question="question" :questions="questions" @answer="onAnswer" />

        <fieldset class="card card-pad stack" :disabled="busy || !!already">
          <ItemForm :draft="draft" :errors="errors" :flags="flags" @update:draft="onDraft" @fields="fields = $event" />
          <OccasionPicker :model-value="draft.occasion_id" @update:model-value="onDraft({ ...draft, occasion_id: $event })" />
        </fieldset>
      </template>

      <section v-if="already" class="notice notice-info" role="status">
        Already saved, from another tab or an earlier tap:
        <RouterLink v-for="it in already" :key="it.id" :to="`/items/${it.id}`" class="saved-link">{{ it.name }}</RouterLink>
      </section>
      <p v-else-if="error" class="notice notice-error" role="alert">{{ error }}</p>

      <div v-if="!already" class="actions">
        <button type="button" class="btn btn-danger-quiet" :disabled="busy" @click="asking = true">Discard</button>
        <button type="button" class="btn btn-primary" :disabled="busy || !canSave" @click="save">{{ busy ? 'Saving…' : 'Save item' }}</button>
      </div>
      <button v-else type="button" class="btn btn-primary btn-block" @click="$emit('finished', { saved: 0 })">Next</button>
    </div>

    <ConfirmSheet :open="asking" title="Discard this card?" confirm-label="Discard" :busy="busy" :error="discardError"
      @cancel="asking = false; discardError = ''" @confirm="discard">
      The photo is deleted and nothing is saved.
    </ConfirmSheet>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import ConfirmSheet from './ConfirmSheet.vue'
import FollowUps from './FollowUps.vue'
import IntakePhoto from './IntakePhoto.vue'
import ItemForm from './ItemForm.vue'
import OccasionPicker from './OccasionPicker.vue'
import { api } from '../lib/backend'
import { categoryFields, cleanDraft } from '../lib/categories'
import { answer, cardToDraft, clearFlags, confirmItem, followUps, itemErrors } from '../lib/intake'
import { forgetDraft, loadDraft, saveDraft } from '../lib/intakeDrafts'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['finished'])

const card = computed(() => (props.job.status === 'needs_review' ? props.job.card : null))
const draft = ref(null)
const flags = ref({})
const question = ref('')
const fields = ref([])
const ready = ref(false)

onMounted(async () => {
  const kept = loadDraft(props.job.id)
  const catId = kept?.draft?.category_id || card.value?.category_id
  fields.value = catId ? await categoryFields(catId).catch(() => []) : []
  if (kept?.kind === 'single') {
    ({ draft: draft.value, flags: flags.value, question: question.value } = kept)
  } else {
    const made = cardToDraft(card.value, fields.value, { occasionId: props.job.occasion_id || '' })
    draft.value = made.draft
    flags.value = made.flags
    question.value = made.question
  }
  ready.value = true
})

watch([draft, flags], () => {
  if (ready.value) saveDraft(props.job.id, { kind: 'single', draft: draft.value, flags: flags.value, question: question.value })
}, { deep: true })

const sureness = computed(() => ({
  high: 'The AI is sure what this is. Check the details before saving.',
  medium: 'The AI is fairly sure. Check the marked values.',
  low: "The AI wasn't sure. Check everything, especially the marked values.",
}[card.value?.confidence] || ''))

const questions = computed(() => (draft.value ? followUps(draft.value, fields.value) : []))
const canSave = computed(() => draft.value && draft.value.name.trim() && draft.value.category_id)

function onDraft(next) {
  flags.value = clearFlags(draft.value, next, flags.value)
  draft.value = next
}
const onAnswer = (key, value) => onDraft(answer(draft.value, key, value))

const busy = ref(false)
const error = ref('')
const errors = ref({})
const already = ref(null)

async function save() {
  if (!canSave.value) return
  busy.value = true
  error.value = ''
  errors.value = {}
  try {
    const { items } = await api.confirmIntakeJob(props.job.id, [confirmItem(await cleanDraft(draft.value))])
    forgetDraft(props.job.id)
    emit('finished', { saved: items.length, items })
  } catch (e) {
    if (e.status === 409 && e.body?.detail?.job?.status === 'done') {
      forgetDraft(props.job.id)
      already.value = e.body.detail.job.items
    } else {
      errors.value = itemErrors(e.body)[0] || {}
      error.value = Object.keys(errors.value).length ? 'Some details need fixing. See the messages next to the fields.' : e.message
    }
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
.review { display: grid; gap: 16px; }
fieldset { border: 1px solid var(--line); margin: 0; min-width: 0; }
.actions { display: grid; grid-template-columns: 1fr 2fr; gap: 8px; }
.saved-link { display: block; margin-top: 4px; font-weight: 600; }
/* Side by side when there is room: the photo stays in view while you scroll the form. */
@media (min-width: 900px) {
  .review { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
  .photo { position: sticky; top: 72px; }
}
</style>
