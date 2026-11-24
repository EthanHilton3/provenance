import { createClient } from '@supabase/supabase-js'

const url = (import.meta.env.VITE_SUPABASE_URL || '').trim()
const anonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || '').trim()

const validUrl = /^https?:\/\/[^\s"']+$/.test(url)
export const configured = Boolean(validUrl && anonKey)
if (!configured) {
  // Vite reads frontend/.env.local at startup; restart the dev server after editing it.
  console.error('Supabase is not configured: set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env.local')
}

// A placeholder URL keeps createClient from throwing, so the sign-in screen can say what is missing.
export const supabase = createClient(validUrl ? url : 'http://localhost', anonKey || 'missing')
