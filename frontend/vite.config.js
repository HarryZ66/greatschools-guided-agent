import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run dev` sends /api to the agent: a local one by default, or set API_URL to the
// deployed CloudFront URL, e.g. API_URL=https://dxxxx.cloudfront.net npm run dev
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: process.env.API_URL || 'http://localhost:8000', changeOrigin: true, secure: true },
    },
  },
})
