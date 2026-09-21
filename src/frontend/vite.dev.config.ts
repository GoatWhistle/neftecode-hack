import { defineConfig, mergeConfig } from "vite";
import { config } from "./vite.config";

export default mergeConfig(config, defineConfig({
  server: {
    port: 5174,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8080" }
  }
}));
