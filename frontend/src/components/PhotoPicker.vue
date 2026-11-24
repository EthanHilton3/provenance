<!--
  Two ways in: "Take photo" opens the camera directly (capture), "Choose photos" opens the library or files
  (no capture, so the phone offers both). On a desktop both open the file picker.
-->
<template>
  <div class="row picker">
    <label class="btn btn-soft">
      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>
      Take photo
      <input class="sr-only" type="file" accept="image/*" capture="environment" :disabled="disabled" @change="pick" />
    </label>
    <label class="btn btn-soft">
      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m4 16 5-5 4 4 3-3 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
      Choose photos
      <input class="sr-only" type="file" accept="image/*" multiple :disabled="disabled" @change="pick" />
    </label>
  </div>
</template>

<script setup>
defineProps({ disabled: Boolean })
const emit = defineEmits(['files'])
function pick(e) {
  const files = [...(e.target.files || [])]
  e.target.value = '' // so choosing the same file again still fires
  if (files.length) emit('files', files)
}
</script>

<style scoped>
.picker { flex-wrap: wrap; }
.picker .btn { flex: 1 1 140px; position: relative; }
.picker .btn:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
