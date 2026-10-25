import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
  // Recharts makes the single bundle about 730 kB (215 kB gzipped); that is
  // fine for this dashboard, so only warn above 900 kB.
  build: { chunkSizeWarningLimit: 900 },
  test: { environment: 'node' },
})
