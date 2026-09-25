import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    // MapLibre >= 5 loads its worker via new URL("./maplibre-gl-worker.mjs", import.meta.url); pre-bundling
    // moves the module into .vite/deps and breaks that relative URL ("Worker failed to load").
    optimizeDeps: { exclude: ["maplibre-gl"] },
    worker: { format: "es" },
    server: {
      port: 5173,
      host: true,
      // Same-origin API in development: no CORS, no hard-coded host in the bundle.
      proxy: { "/api": { target: env.VITE_DEV_API_PROXY || "http://localhost:8000", changeOrigin: true } },
    },
    build: {
      sourcemap: true,
      chunkSizeWarningLimit: 1200,
      rollupOptions: { output: { manualChunks: { maplibre: ["maplibre-gl"], react: ["react", "react-dom", "react-router-dom"] } } },
    },
  };
});
