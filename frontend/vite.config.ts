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
    // Bound to the loopback address explicitly. Vite's default is `localhost`,
    // which Node resolves to whichever family the host's resolver returns first —
    // on a machine whose /etc/hosts lists `::1 localhost`, that is IPv6, and a
    // caller that asks for 127.0.0.1 then waits for a timeout that looks like a
    // hung server. The end-to-end tests probe 127.0.0.1, so the server binds it.
    host: "127.0.0.1",
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
