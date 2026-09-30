import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // In development, forward API calls to the backend so the app and API
    // share an origin (admin session cookies depend on it).
    proxy: { '/api': 'http://localhost:8000' },
  },
});
