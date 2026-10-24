import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";
import type { Accepted, Forecast } from "../src/shared/api";
import { expectStatementPreview, go, login } from "./fixtures/app";

test("new planned expense and cancellation update forecast incrementally through real UI", async ({ page }) => {
  const fixture = scenarioStatement();
  await login(page);
  await go(page, "Импорт данных");
  await expect(page.getByLabel("CSV-файл", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Счёт", exact: true }).selectOption({ label: "Расчётный счёт · RUB" });
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
    name: "incremental-synthetic.csv", mimeType: "text/csv", buffer: fixture.buffer,
  });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expectStatementPreview(page, fixture.rowCount);
  const baseReply = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  const baseAccepted = await (await baseReply).json() as Accepted;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${baseAccepted.job_id}`)).json()).status).toBe("succeeded");
  await go(page, "Прогноз");
  await expect(page.getByTestId("calculation-mode")).toBeVisible();
  const base = await (await page.request.get(`/api/v1/forecasts/${baseAccepted.forecast_run_id}`)).json() as Forecast;
  const due = new Date(Date.parse(fixture.today) + 5 * 86400000).toISOString().slice(0, 10);
  await go(page, "Плановые платежи");
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("10000");
  await page.getByLabel("Плановая дата", { exact: true }).fill(due);
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(`Incremental ${randomUUID()}`);
  const changedReply = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  const planReply = page.waitForResponse(r => r.url().endsWith("/planned-events") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  const plan = await (await planReply).json();
  const changedAccepted = await (await changedReply).json() as Accepted;
  await go(page, "Прогноз");
  await expect(page.getByTestId("calculation-mode")).toContainText("Частичное обновление");
  const updated = await (await page.request.get(`/api/v1/forecasts/${changedAccepted.forecast_run_id}`)).json() as Forecast;
  expect(updated.id).not.toBe(base.id);
  expect(updated.calculation?.mode).toBe("incremental");
  expect(updated.calculation?.reused_history).toBe(true);
  expect(updated.calculation?.source_forecast_id).toBeTruthy();
  expect(updated.calculation?.bootstrap_paths_generated).toBe(0);
  for (let i = 0; i < base.points.length; i++) {
    expect(updated.points[i].balance_p50_minor).toBe(base.points[i].balance_p50_minor - (base.points[i].point_date >= due ? 1_000_000 : 0));
  }
  await go(page, "Плановые платежи");
  const cancelReply = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByTestId(`planned-event-${plan.id}`).getByRole("button", { name: "Отменить", exact: true }).click();
  const cancelled = await (await cancelReply).json() as Accepted;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${cancelled.job_id}`)).json()).status).toBe("succeeded");
  const restored = await (await page.request.get(`/api/v1/forecasts/${cancelled.forecast_run_id}`)).json() as Forecast;
  expect(restored.calculation?.mode).toBe("incremental");
  expect(restored.points).toEqual(base.points);
  expect(await (await page.request.get(`/api/v1/forecasts/${base.id}`)).json()).toEqual(base);
});
