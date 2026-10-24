import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";
import { login, go, expectStatementPreview } from "./fixtures/app";
import type { Accepted } from "../src/shared/api";
import type { CashGapReport } from "../src/features/forecast/cash-gaps";

test("cash gap: real import, worker, episode and financing preview preserve saved plans", async ({ page }) => {
  const fixture = scenarioStatement();
  const day = (offset: number) => new Date(Date.parse(fixture.today) + offset * 86400000).toISOString().slice(0, 10);
  await login(page);
  await page.getByRole("combobox", { name: "Счёт", exact: true }).selectOption({ label: "Расчётный счёт · RUB" });
  await go(page, "Импорт данных");
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
    name: "cash-gap-synthetic.csv", mimeType: "text/csv", buffer: fixture.buffer,
  });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expectStatementPreview(page, fixture.rowCount);
  const importedForecast = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  expect((await importedForecast).status()).toBe(202);
  await expect(page.getByText(/Результат сохранённого импорта/)).toBeVisible();
  await go(page, "Прогноз");
  await expect(page.getByTestId("cash-gap-panel").getByText("Исходный прогноз", { exact: true })).toBeVisible();
  await go(page, "Плановые платежи");
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("9000000");
  await page.getByRole("combobox", { name: "Категория плана", exact: true }).selectOption("purchases");
  await page.getByLabel("Плановая дата", { exact: true }).fill(day(5));
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(`Gap synthetic ${randomUUID()}`);
  const planReply = page.waitForResponse(r => r.url().endsWith("/planned-events") && r.request().method() === "POST");
  const forecastReply = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  const plan = await (await planReply).json();
  try {
    const accepted = await (await forecastReply).json() as Accepted;
    await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${accepted.job_id}`)).json()).status,
      { timeout: 30000 }).toBe("succeeded");
    await go(page, "Прогноз");
    const path = `/api/v1/forecasts/${accepted.forecast_run_id}`;
    const panel = page.getByTestId("cash-gap-panel");
    await expect(panel).toContainText("Есть дефицит по медиане");
    const original = await (await page.request.get(`${path}/cash-gaps`)).json() as CashGapReport;
    expect(original.base.first_new_gap_date).toBe(day(5));
    expect(original.base.days_until_new_gap).toBe(5);
    expect(original.base.required_reserve_minor).toBe(original.base.max_deficit_minor);
    expect(original.probability_status).toBe("estimated_uncalibrated");
    expect(original.probability).toBe(1);
    await expect(panel.getByTestId("gap-probability")).toContainText(/100\s*%/);
    await expect(page.getByTestId("probability-notice")).toContainText("не откалибрована");
    await expect(panel).toContainText("От даты среза до нового разрыва: 5 дн.");
    await expect(panel).toContainText("Резерв на начало прогноза");
    const company = await page.getByRole("combobox", { name: "Компания", exact: true }).inputValue();
    const before = await (await page.request.get(`/api/v1/companies/${company}/planned-events`)).json();
    await panel.getByLabel("Сумма финансирования, ₽", { exact: true }).fill("10000000");
    await panel.getByLabel("Дата получения", { exact: true }).fill(day(1));
    await panel.getByLabel("Дата возврата", { exact: true }).fill(day(40));
    // Нулевая стоимость по умолчанию допустима; это регрессия независимого ревью.
    const resultReply = page.waitForResponse(r => r.url().endsWith("/cash-gap-preview"));
    await panel.getByRole("button", { name: "Проверить действие", exact: true }).click();
    const response = await resultReply;
    expect(response.status()).toBe(200);
    const result = await response.json() as CashGapReport;
    expect(result.base).toEqual(original.base);
    expect(result.preview.max_deficit_minor).toBe(0);
    expect(result.debt_beyond_horizon_minor).toBe(1_000_000_000);
    await expect(panel.getByTestId("cash-gap-comparison")).toContainText("Платежи не изменены");
    await expect(panel.getByRole("img", { name: "Сравнение остатков до и после действия" })).toBeVisible();
    expect(await (await page.request.get(`${path}/cash-gaps`)).json()).toEqual(original);
    expect(await (await page.request.get(`/api/v1/companies/${company}/planned-events`)).json()).toEqual(before);
    await panel.getByLabel("Полная стоимость финансирования, ₽", { exact: true }).fill("100");
    await expect(panel.getByTestId("cash-gap-comparison")).toHaveCount(0);
    const paidReply = page.waitForResponse(r => r.url().endsWith("/cash-gap-preview"));
    await panel.getByRole("button", { name: "Проверить действие", exact: true }).click();
    expect((await (await paidReply).json()).debt_beyond_horizon_minor).toBe(1_000_010_000);
    await panel.getByRole("combobox", { name: "Действие", exact: true }).selectOption("delay");
    const purchase = original.flows.find(f => f.amount_minor === -900_000_000)!;
    expect(purchase.delay_allowed).toBe(true);
    await panel.getByRole("combobox", { name: "Поток", exact: true }).selectOption(purchase.id);
    await panel.getByRole("checkbox").check();
    await panel.getByLabel("Новая дата", { exact: true }).fill(day(6));
    const delayedReply = page.waitForResponse(r => r.url().endsWith("/cash-gap-preview"));
    await panel.getByRole("button", { name: "Проверить действие", exact: true }).click();
    const delayed = await (await delayedReply).json() as CashGapReport;
    expect(delayed.preview.first_new_gap_date).toBe(day(6));
    expect(delayed.base).toEqual(original.base);
    expect(await (await page.request.get(`/api/v1/companies/${company}/planned-events`)).json()).toEqual(before);
  } finally {
    await go(page, "Плановые платежи");
    await page.getByTestId(`planned-event-${plan.id}`).getByRole("button", { name: "Отменить", exact: true }).click();
  }
});
