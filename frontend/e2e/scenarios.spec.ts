import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";
import { expectStatementPreview, go, login } from "./fixtures/app";

// Стабильные ID и остатки не удваивают операции при повторе на том же стенде.
test("all four scenario forms use the saved base through a real worker", async ({ page }) => {
  const tag = randomUUID();
  const { today, rowCount, buffer } = scenarioStatement();
  const due = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
  await login(page);
  await go(page, "Импорт данных");
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
    name: "scenarios.csv", mimeType: "text/csv", buffer,
  });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expectStatementPreview(page, rowCount);
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Добавлено:" })).toBeVisible();
  await go(page, "Плановые платежи");
  await page.getByRole("combobox", { name: "Движение по плану", exact: true }).selectOption("in");
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("123,45");
  await page.getByLabel("Плановая дата", { exact: true }).fill(due);
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(`Сценарий ${tag}`);
  const eventResponse = page.waitForResponse(r => r.url().endsWith("/planned-events") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  const eventId = (await (await eventResponse).json()).id as string;
  await go(page, "Прогноз");
  await expect(page.getByLabel("Дата среза", { exact: true })).toHaveValue(today);
  const forecastResponse = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  const baseId = (await (await forecastResponse).json()).forecast_run_id as string;
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  const original = await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json();
  await go(page, "Сценарии");
  const kind = page.getByRole("combobox", { name: "Вид сценария", exact: true });
  for (const value of ["add_expense", "delay_event", "reduce_irregular_inflow", "increase_recurring"]) {
    await kind.selectOption(value);
    if (value === "add_expense") await page.getByLabel("Дополнительный расход, ₽", { exact: true }).fill("1234,56");
    if (value === "delay_event") {
      await page.getByRole("combobox", { name: "Платёж из базового прогноза", exact: true }).selectOption(eventId);
      await page.getByLabel("Задержка, дней", { exact: true }).fill("7");
    }
    if (value === "reduce_irregular_inflow" || value === "increase_recurring") {
      await page.getByLabel("Изменение, %", { exact: true }).fill("50");
    }
    if (value === "increase_recurring") {
      const target = page.getByRole("combobox", { name: "Платёж из базового прогноза", exact: true });
      const option = target.locator("option").filter({ hasText: "77,77" });
      await expect(option).toHaveCount(1);
      await target.selectOption((await option.getAttribute("value"))!);
    }
    const response = page.waitForResponse(r => r.url().endsWith("/comparison") && r.status() === 200);
    await page.getByRole("button", { name: "Проверить сценарий", exact: true }).click();
    const compared = await (await response).json();
    await expect(page.getByTestId("scenario-comparison")).toBeVisible();
    const deltas = compared.points.map((point: { delta_balance_minor: number }) => point.delta_balance_minor) as number[];
    if (value === "add_expense") expect(deltas.at(-1)).toBe(-123456);
    else if (value === "delay_event") { expect(deltas).toContain(-12345); expect(deltas.at(-1)).toBe(0); }
    else expect(deltas.at(-1)).toBeLessThan(0);
    expect(compared.base_forecast_id).toBe(baseId);
    expect(compared.points).toHaveLength(30);
  }
  expect(await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json()).toEqual(original);
  await go(page, "Плановые платежи");
  await page.getByRole("table", { name: "Плановые платежи", exact: true }).getByRole("row")
    .filter({ hasText: `Сценарий ${tag}` }).getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(page.getByRole("table", { name: "Плановые платежи", exact: true }).getByRole("row")
    .filter({ hasText: `Сценарий ${tag}` })).toContainText("Отменён");
});
