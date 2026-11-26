<!--
  "This looks like an existing release; use it?" (S12). Shown when saving would create a shared release that is
  nearly identical to one already there. You decide: use one of them (your item links to it), or say yours is
  different (it is made, and these are not suggested again). Nothing is ever merged for you.
-->
<template>
  <section class="notice notice-info stack" role="group" aria-labelledby="dup-title">
    <p id="dup-title"><strong>This looks like a release that's already in the shared catalog.</strong> Use it?</p>
    <div v-for="s in similar" :key="s.id" class="row">
      <span class="what">{{ releaseLine(s) }}</span>
      <button type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="$emit('use', s.id)">Use this one</button>
    </div>
    <p class="muted small">Only use it if it's the same edition and format as yours.</p>
    <div class="two">
      <button type="button" class="btn btn-soft" :disabled="busy" @click="$emit('cancel')">Back to the card</button>
      <button type="button" class="btn btn-soft" :disabled="busy" @click="$emit('different')">No, mine is different</button>
    </div>
  </section>
</template>

<script setup>
import { releaseLine } from '../lib/catalog'

defineProps({ similar: { type: Array, required: true }, busy: { type: Boolean, default: false } })
defineEmits(['use', 'different', 'cancel'])
</script>

<style scoped>
.row { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; }
.what { font-weight: 600; overflow-wrap: anywhere; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
</style>
