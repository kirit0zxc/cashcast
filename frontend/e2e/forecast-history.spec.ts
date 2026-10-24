import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("saved history paginates after reload and opens base/scenario without enqueue", async ({ page }) => {
  const tag = randomUUID();
  const today = new Date().toISOString().slice(0, 10);
  const due = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Движение по плану", exact: true }).selectOption("in");
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("12,34");
  await page.getByLabel("Плановая дата", { exact: true }).fill(due);
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(`История ${tag}`);
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  const planRow = page.getByRole("table", { name: "Плановые платежи", exact: true }).getByRole("row")
    .filter({ hasText: `История ${tag}` });
  await expect(planRow).toBeVisible();
  await page.getByLabel("Дата среза", { exact: true }).fill(today);
  const response = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  const baseId = (await (await response).json()).forecast_run_id as string;
  const chart = page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true });
  await expect(chart).toBeVisible();
  const original = await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json();
  const user = await (await page.request.get("/api/v1/auth/me")).json();
  const companyId = await page.getByRole("combobox", { name: "Компания", exact: true }).inputValue();
  const accountId = await page.getByRole("combobox", { name: "Счёт", exact: true }).inputValue();
  const headers = { "X-CSRF-Token": user.csrf_token };
  // Новые сохранённые расчёты вытесняют выбранную базу на вторую страницу.
  for (let seed = 1000; seed < 1012; seed++) {
    const queued = await page.request.post(`/api/v1/companies/${companyId}/forecasts`, {
      headers, data: { account_id: accountId, as_of: today, horizon_days: 30, seed },
    });
    expect(queued.status()).toBe(202);
  }
  const scenarioResponse = await page.request.post(`/api/v1/forecasts/${baseId}/scenarios`, {
    headers, data: { changes: [{ kind: "add_expense", amount_minor: 1234, on_date: due }] },
  });
  expect(scenarioResponse.status()).toBe(202);
  const scenario = await scenarioResponse.json();
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${scenario.job_id}`)).json()).status,
    { timeout: 30000 }).toBe("succeeded");
  await page.reload();
  let enqueues = 0;
  page.on("request", request => {
    if (request.method() === "POST" && /\/(forecasts|scenarios)$/.test(new URL(request.url()).pathname)) enqueues++;
  });
  await page.getByText("История расчётов", { exact: true }).click();
  await expect(page.getByTestId(`history-row-${scenario.forecast_run_id}`)).toBeVisible();
  await page.getByTestId(`history-row-${scenario.forecast_run_id}`).getByRole("button", { name: "Открыть", exact: true }).click();
  await expect(chart).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Вид сценария", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Открыть исходный прогноз", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Вид сценария", exact: true })).toBeVisible();
  await expect(page.getByTestId(`history-row-${baseId}`)).toHaveCount(0);
  await page.getByRole("button", { name: "Следующие 10 расчётов", exact: true }).click();
  await expect(page.getByTestId(`history-row-${baseId}`)).toBeVisible();
  await page.getByTestId(`history-row-${baseId}`).getByRole("button", { name: "Открыть", exact: true }).click();
  await expect(chart).toBeVisible();
  expect(await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json()).toEqual(original);
  expect(enqueues).toBe(0);
  await planRow.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(planRow).toContainText("Отменён");
});
