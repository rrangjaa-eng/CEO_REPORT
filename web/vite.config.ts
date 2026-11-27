/// <reference types="vitest/config" />
import { defineConfig } from "vite";

export default defineConfig({
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false },
  test: { environment: "node" },
});
