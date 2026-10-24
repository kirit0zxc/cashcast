import { defineConfig } from "@playwright/test";
import { env } from "node:process";

// E2E идут в отдельном Compose project; тестовый CSV синтетический и не содержит данных ZIP.
export default defineConfig({
  testDir: "./e2e", timeout: 60_000, workers: 1, retries: 0,
  use: { baseURL: env.CC_E2E_BASE_URL ?? "http://127.0.0.1:18081", browserName: "chromium", headless: true },
  reporter: "list",
});
