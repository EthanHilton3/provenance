<!-- The fields you fill in by hand, shared by Add and Edit. The category's own fields come from CategoryFields. -->
<template>
  <div class="stack">
    <label class="field">
      <span>Name</span>
      <input class="input" :value="draft.name" required maxlength="300" placeholder="e.g. Spirited Away, 4K steelbook"
        @input="patch({ name: $event.target.value })" />
    </label>

    <CategoryPicker :model-value="draft.category_id" @update:model-value="patch({ category_id: $event })" />

    <CategoryFields v-if="draft.category_id" :category-id="draft.category_id" :model-value="draft.attributes" editable
      @update:model-value="patch({ attributes: $event })" />

    <label class="field">
      <span>Condition</span>
      <select class="input" :value="draft.condition_grade || ''" @change="patch({ condition_grade: $event.target.value })">
        <option value="">Not set</option>
        <option v-for="[v, label] in CONDITIONS" :key="v" :value="v">{{ label }}</option>
      </select>
    </label>

    <label class="check">
      <input type="checkbox" :checked="draft.sealed" @change="patch({ sealed: $event.target.checked })" />
      <span>Still sealed</span>
    </label>

    <div class="two">
      <label class="field">
        <span>Acquired</span>
        <input class="input" type="date" :value="draft.acquired_on || ''" @input="patch({ acquired_on: $event.target.value })" />
      </label>
      <label class="field">
        <span>Where from</span>
        <input class="input" :value="draft.source || ''" maxlength="300" placeholder="Gift, eBay, Target…"
          @input="patch({ source: $event.target.value })" />
      </label>
    </div>

    <label class="field">
      <span>Notes</span>
      <textarea class="input" :value="draft.notes || ''" maxlength="5000" @input="patch({ notes: $event.target.value })" />
    </label>
  </div>
</template>

<script setup>
import { CONDITIONS } from '../lib/item'
import CategoryFields from './CategoryFields.vue'
import CategoryPicker from './CategoryPicker.vue'

const props = defineProps({ draft: { type: Object, required: true } })
const emit = defineEmits(['update:draft'])
const patch = (changes) => emit('update:draft', { ...props.draft, ...changes })
</script>

<style scoped>
/* Side by side only when there is room: a phone's date picker is wider than half the screen.
   minmax(0, 1fr) lets a column shrink below its content instead of spilling into the next one. */
.two { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); }
@media (min-width: 520px) { .two { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
</style>
