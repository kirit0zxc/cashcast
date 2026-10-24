import { defineConfig } from "@playwright/test";
import { env } from "node:process";

// Изолированная проверка UI на синтетических ответах API, без БД и внешнего ИИ.
export default defineConfig({
  testDir: "./e2e", testMatch: "readability.spec.ts", workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:18158", browserName: "chromium", channel: env.CC_E2E_CHANNEL, headless: true },
  webServer: { command: "npm run dev -- --port 18158", url: "http://127.0.0.1:18158", reuseExistingServer: false },
  reporter: "list",
});
