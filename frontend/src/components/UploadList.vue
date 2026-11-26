<template>
  <ul v-if="list.length" class="uploads">
    <li v-for="e in list" :key="e.key" :class="['up', e.status]">
      <img v-if="e.preview" :src="e.preview" alt="" class="thumb" @error="e.preview = null" />
      <div v-else class="thumb blank" aria-hidden="true">IMG</div>
      <div class="body">
        <p class="name">{{ e.name }}</p>
        <div v-if="e.status === 'uploading' || e.status === 'processing'" class="bar" role="progressbar"
          :aria-valuenow="Math.round(e.progress * 100)" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${Math.round(e.progress * 100)}%` }" />
        </div>
        <p class="status small" :class="{ err: e.status === 'error' }" aria-live="polite">{{ statusText(e) }}</p>
      </div>
      <button v-if="e.status === 'waiting' || e.status === 'error'" type="button" class="btn btn-quiet btn-sm"
        :aria-label="`Remove ${e.name}`" @click="$emit('remove', e)">✕</button>
    </li>
  </ul>
</template>

<script setup>
const props = defineProps({ list: { type: Array, required: true }, waitingText: { type: String, default: 'Uploads after you save' } })
defineEmits(['remove'])

function statusText(e) {
  switch (e.status) {
    case 'waiting': return props.waitingText
    case 'uploading': return `Uploading… ${Math.round(e.progress * 100)}%`
    case 'processing': return 'Processing…'
    case 'done': return 'Uploaded'
    case 'error': return e.error || 'Upload failed'
  }
}
</script>

<style scoped>
.uploads { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.up { display: flex; align-items: center; gap: 12px; padding: 8px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); }
.up.error { border-color: var(--danger); }
.thumb { width: 52px; height: 52px; border-radius: 8px; object-fit: cover; flex: none; background: var(--surface-2); }
.blank { display: grid; place-items: center; font-size: 11px; color: var(--faint); }
.body { flex: 1; min-width: 0; display: grid; gap: 4px; }
.name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.95rem; }
.status { color: var(--muted); }
.status.err { color: var(--danger); }
.done .status { color: var(--accent); }
.bar { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); transition: width 0.15s; }
.processing .bar span { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.45; } }
</style>
