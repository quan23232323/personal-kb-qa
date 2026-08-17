import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发环境通过 proxy 转发 /api 到后端，避免跨域；后端也启用了 CORS 作为兜底。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
