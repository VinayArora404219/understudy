import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// VITE_API=mock (default) serves the UI against an in-browser mock of the API, so the frontend can be
// built and reviewed before the backend exists. VITE_API=live proxies /api to the FastAPI server.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { target: "es2022" }, // the API module picks mock or live with a top-level await
  server: {
    port: 5180,
    // RECAST_API points the dev server at another backend (e.g. a second one with judge links on)
    proxy: { "/api": { target: process.env.RECAST_API ?? "http://127.0.0.1:8780", changeOrigin: false } },
  },
});
