import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// `npm run dev:web` serves the interface with hot reload against a backend
// started separately (see README, Development). PHONEVITALS_BACKEND overrides
// its address.
const backend = process.env.PHONEVITALS_BACKEND || 'http://127.0.0.1:8731';

export default defineConfig({
  root: 'web',
  base: './',
  plugins: [svelte()],
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    target: 'chrome130',
    assetsDir: 'assets',
  },
  server: {
    // Same host as the backend, so its session cookie applies here too.
    host: '127.0.0.1',
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
});
