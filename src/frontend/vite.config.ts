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
    minify: false,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]"
      }
    }
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765"
    }
  }
});

export default config;
