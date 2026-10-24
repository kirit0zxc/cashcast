import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { env } from "node:process";

// Один origin сохраняет cookie-сессию. Порт занят — останавливаемся, а не открываем соседний проект.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": { target: env.CC_DEV_API_TARGET ?? "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
});
