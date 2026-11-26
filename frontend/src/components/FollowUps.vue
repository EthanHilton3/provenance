<!--
  The one-tap follow-up: the AI's own question as it wrote it (it may ask anything, so it's shown, not answered
  automatically), then tap-to-answer questions built in code from what the card is missing (lib/intake.js followUps).
-->
<template>
  <section v-if="aiQuestion || questions.length" class="followups" aria-label="Questions about this item">
    <p v-if="aiQuestion" class="ai"><span class="who">The AI asks</span> {{ aiQuestion }}</p>
    <div v-for="q in questions" :key="q.key" class="q">
      <span class="label">{{ q.question }}</span>
      <div class="chips">
        <button v-for="o in q.options" :key="o.label" type="button" class="chip" @click="$emit('answer', q.key, o.value)">{{ o.label }}</button>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  aiQuestion: { type: String, default: '' },
  questions: { type: Array, default: () => [] },
})
defineEmits(['answer'])
</script>

<style scoped>
.followups { display: grid; gap: 12px; padding: 14px; border-radius: 12px; background: var(--accent-soft); }
.ai { font-weight: 500; }
.who { display: block; font-size: 0.8rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.q { display: grid; gap: 6px; }
</style>
