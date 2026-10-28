import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8787',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2022',
    chunkSizeWarningLimit: 2000,
  },
  optimizeDeps: {
    // onnxruntime-web 由 transformers.js 动态加载，避免预构建破坏 wasm 资源路径
    exclude: ['@huggingface/transformers'],
  },
});
