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

    <!-- On every item, whatever the category: columns, not category fields. Open when one is already filled in. -->
    <details class="more" :open="moreOpen" @toggle="moreOpen = $event.target.open">
      <summary>More details <span class="muted small">franchise, brand, signed by</span></summary>
      <div class="stack more-body">
        <label class="field">
          <span>Franchise / series</span>
          <input class="input" :value="draft.franchise || ''" maxlength="300" placeholder="e.g. Zelda, Star Wars"
            @input="patch({ franchise: $event.target.value })" />
        </label>
        <label class="field">
          <span>Brand / maker</span>
          <input class="input" :value="draft.brand || ''" maxlength="300" placeholder="e.g. Nintendo, LEGO, Pyrex"
            @input="patch({ brand: $event.target.value })" />
        </label>
        <label class="field">
          <span>Signed by</span>
          <input class="input" :value="draft.signed_by || ''" maxlength="300" placeholder="Who signed it, if anyone"
            @input="patch({ signed_by: $event.target.value })" />
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
import { ref } from 'vue'
import { CONDITIONS, MORE_DETAILS } from '../lib/item'
import CategoryFields from './CategoryFields.vue'
import CategoryPicker from './CategoryPicker.vue'

const props = defineProps({ draft: { type: Object, required: true } })
const emit = defineEmits(['update:draft'])
const patch = (changes) => emit('update:draft', { ...props.draft, ...changes })

const moreOpen = ref(MORE_DETAILS.some((k) => String(props.draft[k] ?? '').trim()))
</script>

<style scoped>
.more { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 4px 0; }
.more summary { min-height: 44px; display: flex; align-items: center; gap: 8px; font-weight: 600; cursor: pointer; }
.more-body { padding: 4px 0 16px; }
/* Side by side only when there is room: a phone's date picker is wider than half the screen.
   minmax(0, 1fr) lets a column shrink below its content instead of spilling into the next one. */
.two { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); }
@media (min-width: 520px) { .two { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
</style>
