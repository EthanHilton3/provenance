/** The app's API client: the token comes from the Supabase session, and a 401 sends you back to sign in. */
import { createApi } from './api'
import { accessToken, signOut } from './auth'
import router from '../router'

export const api = createApi({
  getToken: accessToken,
  onUnauthorized: async () => {
    await signOut()
    const here = router.currentRoute.value
    if (here.name !== 'signin') router.replace({ name: 'signin', query: { redirect: here.fullPath, expired: '1' } })
  },
})
