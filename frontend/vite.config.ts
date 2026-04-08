import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import ui from '@nuxt/ui/vite'
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [vue(), ui({ colorMode: false }), tailwindcss()],
  resolve: {
    alias: { "@": resolve(__dirname, "src") },
  },
  optimizeDeps: {
    include: [
      '@nuxt/ui > prosemirror-state',
      '@nuxt/ui > prosemirror-transform',
      '@nuxt/ui > prosemirror-model',
      '@nuxt/ui > prosemirror-view',
      '@nuxt/ui > prosemirror-gapcursor',
    ],
  },
  server: {
    port: 5175,
    proxy: {
      "/v1": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
