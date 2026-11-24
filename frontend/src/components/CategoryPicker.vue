<template>
  <label class="field">
    <span>Category</span>
    <select class="input" :value="modelValue" required @change="$emit('update:modelValue', $event.target.value)">
      <option value="" disabled>Choose a category</option>
      <optgroup v-for="p in categories.list" :key="p.id" :label="p.name">
        <option :value="p.id">{{ p.name }}{{ p.children.length ? ' (general)' : '' }}</option>
        <option v-for="c in p.children" :key="c.id" :value="c.id">{{ c.name }}</option>
      </optgroup>
    </select>
  </label>
</template>

<script setup>
import { categories } from '../lib/categories'

defineProps({ modelValue: { type: String, default: '' } })
defineEmits(['update:modelValue'])
</script>
