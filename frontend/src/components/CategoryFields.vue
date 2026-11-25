<!--
  Renders and edits one category's fields (item.attributes). This is the single place that knows about field
  types.

  Contract (keep it when swapping):
    props:  categoryId  the item's category; the fields (inherited ones included) are loaded from the API
            modelValue  the attributes object, { key: value }
            editable    false = read-only rows, true = inputs
    emits:  update:modelValue with a new attributes object (blank values are left as '' and removed on save)
            fields      the category's template fields once loaded

  Handles the four template types (text, number, boolean, choice) with plain inputs. A field with show_if appears
  only while its condition holds (lib/fields.js); while hidden it keeps its value, and the views drop it on save
  with cleanForSave(). Values whose key is not in the category's template (an old category's fields, or anything
  intake adds later) are shown as other details, never dropped.
-->
<template>
  <div class="cf">
    <p v-if="error" class="notice notice-error small">Could not load this category's fields. {{ error }}</p>

    <template v-if="editable">
      <template v-for="f in shown" :key="f.key">
        <label v-if="f.type === 'boolean'" class="check">
          <input type="checkbox" :checked="modelValue[f.key] === true" @change="set(f.key, $event.target.checked)" />
          <span>{{ f.label }}</span>
        </label>
        <label v-else class="field">
          <span>{{ f.label }}</span>
          <select v-if="f.type === 'choice'" class="input" :value="modelValue[f.key] ?? ''" @change="set(f.key, $event.target.value)">
            <option value="">—</option>
            <option v-for="o in optionsFor(f)" :key="o" :value="o">{{ o }}</option>
          </select>
          <input v-else-if="f.type === 'number'" class="input" type="number" inputmode="decimal" step="any"
            :value="modelValue[f.key] ?? ''" @input="setNumber(f.key, $event.target.value)" />
          <input v-else class="input" type="text" :value="modelValue[f.key] ?? ''" @input="set(f.key, $event.target.value)" />
        </label>
      </template>
      <div v-if="extras.length" class="extras">
        <p class="label">Other details</p>
        <label v-for="[k, v] in extras" :key="k" class="field">
          <span>{{ k }}</span>
          <input class="input" type="text" :value="v" @input="set(k, $event.target.value)" />
        </label>
      </div>
    </template>

    <dl v-else-if="readRows.length" class="rows">
      <div v-for="r in readRows" :key="r.key" class="r">
        <dt>{{ r.label }}</dt>
        <dd>{{ r.value }}</dd>
      </div>
    </dl>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { categoryFields } from '../lib/categories'
import { visibleFields } from '../lib/fields'

const props = defineProps({
  categoryId: { type: String, default: '' },
  modelValue: { type: Object, default: () => ({}) },
  editable: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'fields'])

const fields = ref([])
const error = ref('')

watch(() => props.categoryId, async (id) => {
  error.value = ''
  fields.value = []
  try {
    const loaded = await categoryFields(id)
    if (id === props.categoryId) {
      fields.value = loaded
      emit('fields', loaded)
    }
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true })

const known = computed(() => new Set(fields.value.map((f) => f.key)))
// Hidden conditional fields are known (not extras) but not shown.
const shown = computed(() => visibleFields(fields.value, props.modelValue))
const extras = computed(() => Object.entries(props.modelValue).filter(([k, v]) => !known.value.has(k) && v !== '' && v != null))

// A saved value that is no longer one of the options still shows up in the list, so it isn't silently lost.
function optionsFor(f) {
  const opts = f.options || []
  const v = props.modelValue[f.key]
  return v && !opts.includes(v) ? [...opts, v] : opts
}

function set(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
function setNumber(key, raw) {
  const n = raw === '' ? '' : Number(raw)
  set(key, Number.isNaN(n) ? raw : n)
}

function show(f, v) {
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  return String(v)
}
const readRows = computed(() => {
  const rows = []
  for (const f of shown.value) {
    const v = props.modelValue[f.key]
    if (v === undefined || v === null || v === '') continue
    rows.push({ key: f.key, label: f.label, value: show(f, v) })
  }
  for (const [k, v] of extras.value) rows.push({ key: k, label: k, value: show({}, v) })
  return rows
})
</script>

<style scoped>
.cf { display: grid; gap: 16px; }
.cf:empty { display: none; }
.extras { display: grid; gap: 12px; padding-top: 4px; border-top: 1px dashed var(--line); }
.extras .label { padding-top: 12px; }
.rows { margin: 0; display: grid; }
.r { display: grid; grid-template-columns: minmax(110px, 38%) 1fr; gap: 12px; padding: 10px 0; border-top: 1px solid var(--line); }
.r:first-child { border-top: 0; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
</style>
