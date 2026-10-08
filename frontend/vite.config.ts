import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The backend runs separately on 127.0.0.1:8000. Proxying in development keeps
 * the browser on one origin, so the API's CORS list does not have to grow and
 * the same relative URLs work in the production build behind a reverse proxy.
 */
const BACKEND = process.env.SIGHTOPS_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true }
    }
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true }
    }
  },
  build: {
    outDir: "dist",
    sourcemap: true
  }
});
