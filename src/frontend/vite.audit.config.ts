import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 8893,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8891",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyRes", (res) => {
            res.headers["cache-control"] = "no-cache";
          });
        }
      }
    }
  }
});
