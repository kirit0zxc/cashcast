import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";
import type { Accepted, Forecast } from "../src/shared/api";
import type { PulseReport } from "../src/features/pulse/types";

test("pulse uses saved forecast and planned outflow; buffer reads do not enqueue or rewrite", async ({ page }) => {
  const fixture = scenarioStatement();
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByLabel("CSV-файл", { exact: true })).toBeVisible();
  // Не смешиваем тестовую выписку с другими счетами на демонстрационном стенде.
  await page.getByRole("combobox", { name: "Счёт", exact: true }).selectOption({ label: "Расчётный счёт · RUB" });
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
    name: "pulse-synthetic.csv", mimeType: "text/csv", buffer: fixture.buffer,
  });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expect(page.getByText(new RegExp(`Строк: ${fixture.rowCount}\\. Ошибок: 0`))).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  await expect(page.getByRole("img", { name: "Пульс: сохранённая база и гипотетический план", exact: true })).toBeVisible();

  const due = new Date(Date.parse(fixture.today) + 5 * 86400000).toISOString().slice(0, 10);
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("9000000");
  await page.getByLabel("Плановая дата", { exact: true }).fill(due);
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(`Pulse synthetic ${randomUUID()}`);
  const acceptedReply = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  const planReply = page.waitForResponse(r => r.url().endsWith("/planned-events") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  const plan = await (await planReply).json();
  const accepted = await (await acceptedReply).json() as Accepted;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${accepted.job_id}`)).json()).status).toBe("succeeded");
  const panel = page.getByTestId("pulse-panel");
  await expect(panel).toContainText("Возможная нехватка денег");
  const forecast = await (await page.request.get(`/api/v1/forecasts/${accepted.forecast_run_id}`)).json() as Forecast;
  const pulse = await (await page.request.get(`/api/v1/forecasts/${accepted.forecast_run_id}/pulse`)).json() as PulseReport;
  expect(pulse.cash.chart.base_minor).toEqual(forecast.points.map(p => p.balance_p50_minor));
  expect(pulse.cash.first_gap_date).toBe(forecast.risk.first_negative_date);
  expect(pulse.cash.plan!.credit_cost_minor).toBeGreaterThan(0);
  await panel.getByText("Источники и ограничения пульса", { exact: true }).click();
  await expect(panel).toContainText(accepted.forecast_run_id);
  let posts = 0;
  page.on("request", r => { if (r.method() === "POST") posts++; });
  await panel.getByLabel("Подушка, ₽ (пусто — оценить автоматически)").fill("0");
  const bufferReply = page.waitForResponse(r => r.url().endsWith(`/pulse?buffer_minor=0`));
  await panel.getByRole("button", { name: "Проверить подушку", exact: true }).click();
  expect((await bufferReply).status()).toBe(200);
  await expect(panel).toContainText("задана вами");
  expect(posts).toBe(0);
  expect(await (await page.request.get(`/api/v1/forecasts/${accepted.forecast_run_id}`)).json()).toEqual(forecast);
  // Убираем лишь созданный тестом план штатной кнопкой; старый frozen-пульс сохраняется.
  await page.getByTestId(`planned-event-${plan.id}`).getByRole("button", { name: "Отменить", exact: true }).click();
  expect(await (await page.request.get(`/api/v1/forecasts/${accepted.forecast_run_id}/pulse`)).json()).toEqual(pulse);
});
