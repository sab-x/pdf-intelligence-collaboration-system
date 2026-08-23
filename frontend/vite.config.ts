import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Dev-only mirror of the Vercel same-origin rewrite (PROJECT_PLAN.md §4):
    // the app always calls relative /api/... paths, and this proxy forwards
    // them to the local FastAPI backend so cookies stay first-party in dev too.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
