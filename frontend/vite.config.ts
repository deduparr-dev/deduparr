import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Backend origin the dev/preview server proxies /api to.
// Every deployment that needs a different target sets VITE_PROXY_TARGET: the
// Podman quadlet and the e2e harness both do. The default is therefore what a
// plain `npm run dev` needs, where "backend" does not resolve and every /api
// call came back 502 with an empty body.
const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:3001'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
