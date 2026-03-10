import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri expects the dev server on port 1420.
// TAURI_DEV_HOST is set by `tauri dev` when targeting mobile.
const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: host || false,
    port: 1420,
    strictPort: true,
    // Allow the Tauri window to make requests to the engine
    hmr: host
      ? { protocol: "ws", host, port: 1421 }
      : undefined,
  },
  build: {
    // Tauri supports ES2021+
    target: ["es2021", "chrome100", "safari13"],
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
  envPrefix: ["VITE_", "TAURI_"],
});
