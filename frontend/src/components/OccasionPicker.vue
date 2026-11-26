<!--
  Pick how you got something ("Christmas 2025"), or make a new occasion right here. v-model is an occasion id ('' =
  none). The list is loaded once per session and shared by every picker on the page.
-->
<template>
  <div class="field">
    <label :for="`${uid}-sel`" class="label">{{ label }}</label>
    <select v-if="!adding" :id="`${uid}-sel`" class="input" :value="modelValue || ''" :disabled="disabled" @change="pick($event.target.value)">
      <option value="">{{ noneLabel }}</option>
      <option v-for="o in occasions.list" :key="o.id" :value="o.id">{{ describe(o) }}</option>
      <option value="__new">+ New occasion…</option>
    </select>
    <div v-else class="new card-pad">
      <label class="field">
        <span>Name</span>
        <input ref="nameInput" v-model="name" class="input" maxlength="120" placeholder="e.g. Christmas 2025, Yard sale" @keydown.enter.prevent="add" />
      </label>
      <label class="field">
        <span>Date <span class="muted">optional</span></span>
        <input v-model="date" class="input" type="date" />
      </label>
      <p v-if="error" class="field-error" role="alert">{{ error }}</p>
      <div class="actions">
        <button type="button" class="btn btn-soft" :disabled="busy" @click="cancel">Cancel</button>
        <button type="button" class="btn btn-primary" :disabled="busy || !name.trim()" @click="add">{{ busy ? 'Adding…' : 'Add occasion' }}</button>
      </div>
    </div>
    <p v-if="occasions.error" class="muted small">Could not load your occasions. {{ occasions.error }}</p>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { api } from '../lib/backend'
import { loadOccasions, occasions, remember } from '../lib/occasions'

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, default: 'Occasion' },
  noneLabel: { type: String, default: 'None' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const uid = `op${Math.random().toString(36).slice(2, 8)}`

const adding = ref(false)
const name = ref('')
const date = ref('')
const busy = ref(false)
const error = ref('')
const nameInput = ref(null)

onMounted(loadOccasions)

function describe(o) {
  if (!o.occurred_on) return o.name
  const d = new Date(`${o.occurred_on}T00:00:00`)
  const when = d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  return o.name.includes(String(d.getFullYear())) ? o.name : `${o.name} (${when})`
}

function pick(value) {
  if (value === '__new') {
    adding.value = true
    nextTick(() => nameInput.value?.focus())
    return
  }
  emit('update:modelValue', value)
}

function cancel() {
  adding.value = false
  name.value = ''
  date.value = ''
  error.value = ''
}

async function add() {
  if (!name.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const o = await api.createOccasion({ name: name.value.trim(), ...(date.value ? { occurred_on: date.value } : {}) })
    remember(o)
    emit('update:modelValue', o.id)
    cancel()
  } catch (e) {
    error.value = e.fields?.name || e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.new { display: grid; gap: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-2); }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
</style>
