import { expect, test } from "@playwright/test";
import { go, login } from "./fixtures/app";

test("empty history gives guidance on overview and forecast without enqueue", async ({ page }) => {
  // Контролируем только чтение пустой истории, остальные сервисы настоящие.
  await page.route("**/api/v1/companies/*/forecasts?*", route => route.fulfill({ json: { items: [], next_cursor: null } }));
  let posts = 0;
  page.on("request", r => { if (r.method() === "POST" && r.url().endsWith("/forecasts")) posts++; });
  await login(page);
  await expect(page.getByText("Нет сохранённого прогноза", { exact: true })).toBeVisible();
  await go(page, "Прогноз");
  await expect(page.getByText("Расчёт не выбран", { exact: true })).toBeVisible();
  expect(posts).toBe(0);
});

test("unknown pulse must not promise a safe cushion", async ({ page }) => {
  await login(page);
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const company = await page.getByRole("combobox", { name: "Компания", exact: true }).inputValue();
  const account = await page.getByRole("combobox", { name: "Счёт", exact: true }).inputValue();
  const queued = await page.request.post(`/api/v1/companies/${company}/forecasts`, {
    headers: { "X-CSRF-Token": me.csrf_token },
    data: { account_id: account, as_of: new Date().toISOString().slice(0, 10), horizon_days: 30 },
  });
  expect(queued.status()).toBe(202);
  const accepted = await queued.json();
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${accepted.job_id}`)).json()).status,
    { timeout: 30000 }).toBe("succeeded");
  // Реальный отчёт с контролируемой недоступностью оценки: не маскируем unknown нулём.
  await page.route("**/api/v1/forecasts/*/pulse*", async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.status = data.cash.status = "unknown";
    data.cash.first_gap_date = null; data.cash.plan = null;
    data.cash.message = "Недостаточно данных для прогноза остатка.";
    await route.fulfill({ response, json: data });
  });
  await page.reload();
  await go(page, "Финансовый пульс");
  const panel = page.getByTestId("pulse-panel");
  await expect(panel).toContainText("оценка недоступна");
  await expect(panel).toContainText("План недоступен");
  await expect(panel).not.toContainText("Плана не требуется");
  await expect(panel).not.toContainText("подушка сохраняется");
});
