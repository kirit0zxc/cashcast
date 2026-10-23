import { defineConfig } from "@playwright/test";

// E2E идут в отдельном Compose project; тестовый CSV синтетический и не содержит данных ZIP.
export default defineConfig({
  testDir: "./e2e", timeout: 60_000, workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:18081", browserName: "chromium", headless: true },
  reporter: "list",
});
