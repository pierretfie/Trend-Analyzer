/// <reference types="vite/client" />
import path from "path";
import { fileURLToPath } from "url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  root,
  build: {
    outDir: path.resolve(root, "../trend_analyzer/ui_dist"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 750,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
    },
  },
});
