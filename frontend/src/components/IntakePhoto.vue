<!-- The photo being reviewed. Tap to see it full screen (to read spines on a shelf photo); tap again to close. -->
<template>
  <figure class="ph">
    <button v-if="url && !broken" type="button" class="open" :aria-label="`Show the photo full screen`" @click="big = true">
      <img :src="url" :alt="alt" @error="broken = true" />
    </button>
    <div v-else class="none muted small">{{ url ? 'The photo could not be loaded.' : 'No photo.' }}</div>
    <figcaption v-if="url && !broken" class="muted small">Tap to enlarge</figcaption>
    <Teleport to="body">
      <div v-if="big" class="full" role="dialog" aria-modal="true" aria-label="Photo" tabindex="-1" @click="big = false" @keydown.esc="big = false">
        <img :src="url" :alt="alt" />
        <button type="button" class="btn btn-soft close" @click.stop="big = false">Close</button>
      </div>
    </Teleport>
  </figure>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ url: { type: String, default: '' }, alt: { type: String, default: 'The photo you uploaded' } })
const big = ref(false)
const broken = ref(false)
</script>

<style scoped>
.ph { margin: 0; display: grid; gap: 4px; }
.open { padding: 0; border: 0; background: var(--surface-2); border-radius: var(--radius); overflow: hidden; cursor: zoom-in; }
.open img { width: 100%; max-height: 42vh; object-fit: contain; margin: 0 auto; }
.none { display: grid; place-items: center; min-height: 120px; border-radius: var(--radius); background: var(--surface-2); }
figcaption { text-align: center; }
.full {
  position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; background: rgb(0 0 0 / 0.92);
  overflow: auto; padding: env(safe-area-inset-top) 0 env(safe-area-inset-bottom); cursor: zoom-out;
}
.full img { max-width: none; width: min(100vw, 2048px); height: auto; }
.close { position: fixed; top: calc(env(safe-area-inset-top) + 12px); right: 12px; }
@media (min-width: 900px) { .open img { max-height: 70vh; } }
</style>
