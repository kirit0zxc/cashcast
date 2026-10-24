import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import type { Accepted, Forecast } from "../src/shared/api";
import { scenarioStatement } from "./fixtures/scenario-statement";

// Настоящие API/worker: успешная запись обновляет график, чтение истории не создаёт job.
test("committed facts and plans refresh forecasts automatically without rewriting saved results", async ({ page }) => {
  const fixture = scenarioStatement();
  const tag = randomUUID();
  let forecastRequests = 0;
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/forecasts")) forecastRequests += 1;
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Будущие платежи и обязательства", exact: true })).toBeVisible();

  async function automatic(action: () => Promise<void>) {
    const reply = page.waitForResponse(response => response.url().endsWith("/forecasts")
      && response.request().method() === "POST", { timeout: 7000 });
    await action();
    const response = await reply;
    expect(response.status()).toBe(202);
    const accepted = await response.json() as Accepted;
    await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${accepted.job_id}`)).json()).status,
      { timeout: 15000 }).toBe("succeeded");
    await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
    const result = await (await page.request.get(`/api/v1/forecasts/${accepted.forecast_run_id}`)).json() as Forecast;
    return { accepted, result };
  }

  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
    name: "automatic-synthetic.csv", mimeType: "text/csv", buffer: fixture.buffer,
  });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expect(page.getByText(new RegExp(`Строк: ${fixture.rowCount}\\. Ошибок: 0`))).toBeVisible();
  const base = await automatic(() => page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click());
  expect(base.result.as_of).toBe(fixture.today);
  expect(forecastRequests).toBe(1);
  const due = new Date(Date.parse(fixture.today) + 5 * 86400000).toISOString().slice(0, 10);
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("987,65");
  await page.getByLabel("Плановая дата", { exact: true }).fill(due);
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(`Automatic synthetic ${tag}`);
  const planReply = page.waitForResponse(response => response.url().endsWith("/planned-events")
    && response.request().method() === "POST");
  const changed = await automatic(() => page.getByRole("button", { name: "Добавить платёж", exact: true }).click());
  const plan = await (await planReply).json();
  expect(changed.accepted.forecast_run_id).not.toBe(base.accepted.forecast_run_id);
  expect(changed.result.points.at(-1)!.balance_p50_minor - base.result.points.at(-1)!.balance_p50_minor).toBe(-98765);
  expect(await (await page.request.get(`/api/v1/forecasts/${base.accepted.forecast_run_id}`)).json()).toEqual(base.result);
  expect(forecastRequests).toBe(2);
  const cancelled = await automatic(() => page.getByTestId(`planned-event-${plan.id}`)
    .getByRole("button", { name: "Отменить", exact: true }).click());
  expect(cancelled.result.points.at(-1)!.balance_p50_minor).toBe(base.result.points.at(-1)!.balance_p50_minor);
  expect(await (await page.request.get(`/api/v1/forecasts/${changed.accepted.forecast_run_id}`)).json()).toEqual(changed.result);
  expect(forecastRequests).toBe(3);
  await page.getByLabel("Дата среза", { exact: true }).fill(
    new Date(Date.parse(fixture.today) - 86400000).toISOString().slice(0, 10));
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toHaveCount(0);
  expect(forecastRequests).toBe(3);
  await page.reload();
  await page.getByText("История расчётов", { exact: true }).click();
  await page.getByTestId(`history-row-${cancelled.accepted.forecast_run_id}`)
    .getByRole("button", { name: "Открыть", exact: true }).click();
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  await expect(page.getByLabel("Дата среза", { exact: true })).toHaveValue(fixture.today);
  expect(forecastRequests).toBe(3);
});
