/** Who is signed in. Small enough that a reactive object does the job a store library would. */
import { reactive } from 'vue'
import { supabase } from './supabase'

export const auth = reactive({ user: null, ready: false })

/** Resolves once the saved session (if any) has been read, so the router never guesses. */
export const authReady = (async () => {
  try {
    const { data } = await supabase.auth.getSession()
    auth.user = data.session?.user ?? null
  } catch (e) {
    console.error('Reading the session failed:', e)
  } finally {
    auth.ready = true
  }
  supabase.auth.onAuthStateChange((_event, session) => {
    auth.user = session?.user ?? null
  })
})()

/** The access token for the backend. supabase-js refreshes it first if it is about to expire. */
export async function accessToken() {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

export async function signIn(email, password) {
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) throw error
}

/** Returns true when signed in straight away, false when the project wants the email confirmed first. */
export async function signUp(email, password) {
  const { data, error } = await supabase.auth.signUp({ email, password })
  if (error) throw error
  return Boolean(data.session)
}

export async function signOut() {
  // Clear this device even if the server call fails (offline, session already expired).
  const { error } = await supabase.auth.signOut({ scope: 'local' })
  auth.user = null
  if (error) console.error('Sign out:', error)
}
