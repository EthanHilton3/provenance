<!-- The fields you fill in by hand, shared by Add and Edit. The category's own fields come from CategoryFields. -->
<template>
  <div class="stack">
    <label class="field" :class="{ flagged: flags.name }">
      <span>Name</span>
      <input class="input" :value="draft.name" required maxlength="300" placeholder="e.g. Spirited Away, 4K steelbook"
        @input="patch({ name: $event.target.value })" />
      <span v-if="flags.name" class="flag-note">{{ flags.name }}</span>
      <span v-if="errors.name" class="field-error" role="alert">{{ errors.name }}</span>
    </label>

    <CategoryPicker :model-value="draft.category_id" @update:model-value="patch({ category_id: $event })" />

    <CategoryFields v-if="draft.category_id" :category-id="draft.category_id" :model-value="draft.attributes" :errors="errors"
      :flags="flags" editable @update:model-value="patch({ attributes: $event })" @fields="$emit('fields', $event)" />

    <!-- On every item, whatever the category: columns, not category fields. Open when one is already filled in. -->
    <details class="more" :open="moreOpen" @toggle="moreOpen = $event.target.open">
      <summary>More details <span class="muted small">franchise, brand, signed by</span></summary>
      <div class="stack more-body">
        <label class="field" :class="{ flagged: flags.franchise }">
          <span>Franchise / series</span>
          <input class="input" :value="draft.franchise || ''" maxlength="300" placeholder="e.g. Zelda, Star Wars"
            @input="patch({ franchise: $event.target.value })" />
          <span v-if="errors.franchise" class="field-error" role="alert">{{ errors.franchise }}</span>
        </label>
        <label class="field" :class="{ flagged: flags.brand }">
          <span>Brand / maker</span>
          <input class="input" :value="draft.brand || ''" maxlength="300" placeholder="e.g. Nintendo, LEGO, Pyrex"
            @input="patch({ brand: $event.target.value })" />
          <span v-if="errors.brand" class="field-error" role="alert">{{ errors.brand }}</span>
        </label>
        <label class="field">
          <span>Signed by</span>
          <input class="input" :value="draft.signed_by || ''" maxlength="300" placeholder="Who signed it, if anyone"
            @input="patch({ signed_by: $event.target.value })" />
          <span v-if="errors.signed_by" class="field-error" role="alert">{{ errors.signed_by }}</span>
        </label>
      </div>
    </details>

    <label class="field">
      <span>Condition</span>
      <select class="input" :value="draft.condition_grade || ''" @change="patch({ condition_grade: $event.target.value })">
        <option value="">Not set</option>
        <option v-for="[v, label] in CONDITIONS" :key="v" :value="v">{{ label }}</option>
      </select>
    </label>

    <!-- Three answers, because "not recorded" is real: the AI often can't tell, and a guess must not become a fact. -->
    <div class="field" role="radiogroup" :aria-labelledby="`${uid}-sealed`">
      <span :id="`${uid}-sealed`" class="label">Sealed?</span>
      <div class="seg" :class="{ flagged: flags.sealed }">
        <label v-for="[v, label] in SEALED" :key="label">
          <input type="radio" :name="`${uid}-sealed`" :checked="draft.sealed === v" @change="patch({ sealed: v })" />
          {{ label }}
        </label>
      </div>
      <span v-if="flags.sealed" class="flag-note">{{ flags.sealed }}</span>
    </div>

    <div class="two">
      <label class="field">
        <span>Acquired</span>
        <input class="input" type="date" :value="draft.acquired_on || ''" @input="patch({ acquired_on: $event.target.value })" />
      </label>
      <label class="field">
        <span>Where from</span>
        <input class="input" :value="draft.source || ''" maxlength="300" placeholder="Gift, eBay, Target…"
          @input="patch({ source: $event.target.value })" />
        <span v-if="errors.source" class="field-error" role="alert">{{ errors.source }}</span>
      </label>
    </div>

    <label class="field">
      <span>Notes</span>
      <textarea class="input" :value="draft.notes || ''" maxlength="5000" @input="patch({ notes: $event.target.value })" />
      <span v-if="errors.notes" class="field-error" role="alert">{{ errors.notes }}</span>
    </label>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { CONDITIONS, MORE_DETAILS } from '../lib/item'
import CategoryFields from './CategoryFields.vue'
import CategoryPicker from './CategoryPicker.vue'

// errors: the API's validation errors by field name (lib/api.js fieldErrorsOf), shown next to the input.
// flags: values the AI proposed but may have wrong, keyed the same way (lib/intake.js); each shows why.
const props = defineProps({
  draft: { type: Object, required: true },
  errors: { type: Object, default: () => ({}) },
  flags: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:draft', 'fields'])
const uid = `if${Math.random().toString(36).slice(2, 8)}`
const SEALED = [[null, 'Not recorded'], [true, 'Sealed'], [false, 'Opened']]
const patch = (changes) => emit('update:draft', { ...props.draft, ...changes })

const moreOpen = ref(MORE_DETAILS.some((k) => String(props.draft[k] ?? '').trim()))
</script>

<style scoped>
.more { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 4px 0; }
.more summary { min-height: 44px; display: flex; align-items: center; gap: 8px; font-weight: 600; cursor: pointer; list-style: none; }
.more summary::-webkit-details-marker { display: none; }
.more summary::before {
  content: '›'; display: inline-block; width: 12px; color: var(--muted); font-size: 1.3rem; line-height: 1; transition: transform 0.15s;
}
.more[open] summary::before { transform: rotate(90deg); }
.more-body { padding: 4px 0 16px; }
/* Side by side only when there is room: a phone's date picker is wider than half the screen.
   minmax(0, 1fr) lets a column shrink below its content instead of spilling into the next one. */
.two { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); }
@media (min-width: 520px) { .two { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
</style>
