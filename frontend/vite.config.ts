import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // A fixed port away from Vite's default 5173 range, so it can run next to other local dev servers.
  server: { port: 5280, strictPort: true },
})
