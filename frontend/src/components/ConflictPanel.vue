<!--
  Shown when a save comes back 409: the item was saved somewhere else (another tab, another device) after you
  opened it. Lists what they changed, marks the fields you changed too, and offers the two ways out.
-->
<template>
  <section class="conflict notice-warn" role="alert" aria-labelledby="conflict-title">
    <h2 id="conflict-title">This item changed since you opened it</h2>
    <p class="small">It was saved somewhere else while you were editing. Nothing of yours is saved yet.</p>

    <ul v-if="theirs.length" class="changes">
      <li v-for="c in theirs" :key="c.key">
        <span class="what">{{ c.label }}<em v-if="mine.has(c.key)" class="clash"> · you changed this too</em></span>
        <span class="vals">
          <s>{{ show(c.key, c.from) }}</s>
          <span aria-hidden="true">→</span>
          <strong>{{ show(c.key, c.to) }}</strong>
        </span>
      </li>
    </ul>
    <p v-else class="small muted">The changes were to details this screen doesn't show.</p>

    <div class="actions">
      <button class="btn btn-soft" :disabled="busy" @click="$emit('reload')">Use their version</button>
      <button class="btn btn-primary" :disabled="busy" @click="$emit('overwrite')">
        {{ busy ? 'Saving…' : mine.size ? 'Save my changes on top' : 'Save anyway' }}
      </button>
    </div>
    <p class="small muted">
      "Save my changes on top" keeps their other edits and replaces only the fields you changed{{ clashCount ? ', including the ones marked above' : '' }}.
    </p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { differences, display } from '../lib/item'
import { categoryPath } from '../lib/categories'

const props = defineProps({
  base: { type: Object, required: true },    // the item as you loaded it
  current: { type: Object, required: true }, // the item as it is now
  draft: { type: Object, required: true },   // your unsaved edits
  labelFor: { type: Function, default: () => null },
  busy: Boolean,
})
defineEmits(['reload', 'overwrite'])

const theirs = computed(() => differences(props.base, props.current, props.labelFor))
const mine = computed(() => new Set(differences(props.base, props.draft).map((d) => d.key)))
const clashCount = computed(() => theirs.value.filter((c) => mine.value.has(c.key)).length)
const show = (key, v) => display(key, v, { categoryName: categoryPath })
</script>

<style scoped>
.conflict { display: grid; gap: 12px; padding: 16px; border-radius: var(--radius); }
.changes { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.changes li { display: grid; gap: 2px; padding: 8px 10px; background: var(--surface); border-radius: 8px; }
.what { font-weight: 600; font-size: 0.9rem; }
.clash { font-style: normal; font-weight: 500; color: var(--danger); }
.vals { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; overflow-wrap: anywhere; }
.vals s { color: var(--muted); }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
@media (max-width: 380px) { .actions { grid-template-columns: 1fr; } }
</style>
