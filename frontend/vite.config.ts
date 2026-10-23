import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// dev-прокси: /api на FastAPI, чтобы cookie-сессия работала без CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
