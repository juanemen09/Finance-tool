import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const PROXY = `http://127.0.0.1:${process.env.PORT || 8787}`;

export default defineConfig({
  plugins: [tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': PROXY,
      '/ws': { target: PROXY.replace('http', 'ws'), ws: true },
    },
  },
  build: { target: 'es2022', chunkSizeWarningLimit: 400 },
});
