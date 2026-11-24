import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// The browser only ever talks to /api on its own origin; in development Vite forwards that to FastAPI,
// so there is no CORS to configure. API_TARGET points it at a backend on another port (a test run).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    server: {
      // Its own port, not Vite's default 5173 (Continuity uses that). strictPort: if 5174 is taken, stop with an
      // error rather than quietly sharing or switching ports.
      port: 5174,
      strictPort: true,
      proxy: { '/api': env.API_TARGET || 'http://127.0.0.1:8000' },
    },
  }
})
