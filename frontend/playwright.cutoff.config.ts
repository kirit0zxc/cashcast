import { defineConfig } from "@playwright/test";

// Изолированный UI-тест: все API-ответы задаются в spec, рабочая БД не используется.
export default defineConfig({
  testDir: "./e2e", testMatch: "cutoff-gap-display.spec.ts", workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:5187", browserName: "chromium", headless: true },
  webServer: {
    command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5187",
    url: "http://127.0.0.1:5187", reuseExistingServer: false,
  },
});
