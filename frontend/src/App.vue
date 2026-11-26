<template>
  <div class="app">
    <header v-if="auth.user" class="topbar">
      <RouterLink to="/" class="brand">Provenance</RouterLink>
      <button class="btn btn-quiet btn-sm" @click="leave">Sign out</button>
    </header>
    <main class="page" :class="{ wide: route.meta.wide }">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'
import { auth, signOut } from './lib/auth'

const router = useRouter()
const route = useRoute()
async function leave() {
  await signOut()
  router.replace({ name: 'signin' })
}
</script>
