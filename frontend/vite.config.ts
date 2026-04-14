import dns from "node:dns";
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import ui from '@nuxt/ui/vite'
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

dns.setDefaultResultOrder("verbatim");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const backendOrigin = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:18600";
  const isProductionBuild = mode === "production";

  return {
    // Electron 打包后通过 file:// 加载 index.html，生产产物必须使用相对资源路径。
    base: isProductionBuild ? "./" : "/",
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
      host: "localhost",
      port: 5175,
      strictPort: true,
      proxy: {
        "/v1": { target: backendOrigin, changeOrigin: true },
        "/health": { target: backendOrigin, changeOrigin: true },
      },
    },
  };
});
