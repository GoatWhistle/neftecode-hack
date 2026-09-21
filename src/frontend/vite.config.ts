import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export const config = defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
    modulePreload: { polyfill: false },
    target: "es2022",
    sourcemap: false,
    minify: "esbuild",
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]"
      }
    }
  },
  server: {
    port: 15173,
    proxy: {
      "/api": "http://127.0.0.1:19865"
    }
  }
});

export default config;
