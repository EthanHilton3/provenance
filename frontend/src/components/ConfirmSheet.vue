<!-- A bottom sheet that asks before something can't be undone. Escape or a tap outside cancels. -->
<template>
  <Teleport to="body">
    <div v-if="open" class="scrim" @click.self="$emit('cancel')" @keydown.esc="$emit('cancel')">
      <div ref="sheet" class="sheet card" role="alertdialog" aria-modal="true" :aria-labelledby="id" tabindex="-1">
        <h2 :id="id">{{ title }}</h2>
        <p class="muted"><slot /></p>
        <p v-if="error" class="notice notice-error small">{{ error }}</p>
        <div class="actions">
          <button class="btn btn-soft" :disabled="busy" @click="$emit('cancel')">Cancel</button>
          <button class="btn btn-danger" :disabled="busy" @click="$emit('confirm')">{{ busy ? 'Working…' : confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: Boolean,
  title: { type: String, required: true },
  confirmLabel: { type: String, default: 'Delete' },
  busy: Boolean,
  error: { type: String, default: '' },
})
defineEmits(['confirm', 'cancel'])
const id = `sheet-${Math.random().toString(36).slice(2)}`
const sheet = ref(null)
watch(() => props.open, async (o) => { if (o) { await nextTick(); sheet.value?.focus() } })
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; display: flex; align-items: flex-end; justify-content: center; background: rgb(0 0 0 / 0.35); }
.sheet {
  width: 100%; max-width: 520px; display: grid; gap: 12px; outline: none;
  padding: 20px 16px calc(env(safe-area-inset-bottom) + 16px);
  border-radius: 20px 20px 0 0;
}
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 4px; }
@media (min-width: 560px) { .scrim { align-items: center; } .sheet { border-radius: 20px; } }
</style>
