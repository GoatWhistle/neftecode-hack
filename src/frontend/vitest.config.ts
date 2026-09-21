import { defineConfig, mergeConfig } from "vitest/config";
import { config as viteConfig } from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["src/setupTests.ts"],
      globals: false,
      css: false,
      include: ["src/**/*.test.{ts,tsx}"]
    }
  })
);
