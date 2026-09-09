import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { proxy: { '/api': { target: process.env.FURNITUREOS_API_ORIGIN ?? 'http://127.0.0.1:8000', changeOrigin: true } } },
});
