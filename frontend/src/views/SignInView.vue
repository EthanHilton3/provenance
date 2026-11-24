<template>
  <div class="signin">
    <div class="intro">
      <h1>Provenance</h1>
      <p class="muted">Know exactly what you own, and where it came from.</p>
    </div>

    <form class="card card-pad stack" @submit.prevent="submit">
      <div class="tabs" role="tablist">
        <button type="button" role="tab" :aria-selected="mode === 'in'" :class="{ on: mode === 'in' }" @click="switchTo('in')">Sign in</button>
        <button type="button" role="tab" :aria-selected="mode === 'up'" :class="{ on: mode === 'up' }" @click="switchTo('up')">Create account</button>
      </div>

      <p v-if="!configured" class="notice notice-error">
        Supabase isn't set up: add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to frontend/.env.local and restart the dev server.
      </p>
      <p v-else-if="route.query.expired" class="notice notice-info">Your session ended. Sign in again to carry on.</p>

      <label class="field">
        <span>Email</span>
        <input v-model.trim="email" class="input" type="email" autocomplete="email" inputmode="email" required />
      </label>
      <label class="field">
        <span>Password</span>
        <input v-model="password" class="input" type="password" :autocomplete="mode === 'up' ? 'new-password' : 'current-password'"
          :minlength="mode === 'up' ? 8 : undefined" required />
        <small v-if="mode === 'up'" class="muted small">At least 8 characters.</small>
      </label>

      <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
      <p v-if="checkEmail" class="notice notice-info" role="status">
        Check {{ email }} for a confirmation link, then come back and sign in.
      </p>

      <button class="btn btn-primary btn-block" :disabled="busy || !configured">
        {{ busy ? 'One moment…' : mode === 'in' ? 'Sign in' : 'Create account' }}
      </button>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { signIn, signUp } from '../lib/auth'
import { configured } from '../lib/supabase'

const route = useRoute()
const router = useRouter()
const mode = ref('in')
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const checkEmail = ref(false)

function switchTo(m) {
  mode.value = m
  error.value = ''
  checkEmail.value = false
}

async function submit() {
  error.value = ''
  checkEmail.value = false
  busy.value = true
  try {
    if (mode.value === 'in') {
      await signIn(email.value, password.value)
    } else if (!(await signUp(email.value, password.value))) {
      checkEmail.value = true
      mode.value = 'in'
      return
    }
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/'
    router.replace(redirect)
  } catch (e) {
    error.value = e?.message || 'That did not work. Try again.'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.signin { display: grid; gap: 24px; padding-top: 12vh; max-width: 420px; margin: 0 auto; }
.intro { display: grid; gap: 6px; }
.intro h1 { font-size: 2.1rem; }
.tabs { display: grid; grid-template-columns: 1fr 1fr; background: var(--surface-2); border-radius: 12px; padding: 4px; }
.tabs button {
  min-height: 44px; border: 0; border-radius: 9px; background: transparent; color: var(--muted);
  font: 600 15px var(--font-ui); cursor: pointer;
}
.tabs button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
</style>
