import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";
import type { Accepted, Forecast } from "../src/shared/api";
import { expectStatementPreview, go, login } from "./fixtures/app";

test("imported actual transactions automatically update the saved forecasting state", async ({ page }) => {
  const fixture = scenarioStatement();
  await login(page);
  await go(page, "Импорт данных");
  await expect(page.getByLabel("CSV-файл", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Счёт", exact: true }).selectOption({ label: "Расчётный счёт · RUB" });

  async function upload(buffer: Buffer, rows: number) {
    await go(page, "Импорт данных");
    await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
      name: "incremental-ledger-synthetic.csv", mimeType: "text/csv", buffer,
    });
    await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
    await expectStatementPreview(page, rows);
    const reply = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
    const accepted = await (await reply).json() as Accepted;
    await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${accepted.job_id}`)).json()).status).toBe("succeeded");
    await go(page, "Прогноз");
    await expect(page.getByTestId("calculation-mode")).toBeVisible();
    return await (await page.request.get(`/api/v1/forecasts/${accepted.forecast_run_id}`)).json() as Forecast;
  }

  const initial = await upload(fixture.buffer, fixture.rowCount);
  const makeDelta = () => {
    const tag = randomUUID();
    const lines = ["operation_id;operation_date;amount;direction;counterparty_name;counterparty_inn;payment_purpose;balance_eod",
      `${tag}-in;${fixture.today};100.00;Поступление;Разовый клиент;${tag};Разовый платёж;`,
      `${tag}-out;${fixture.today};100.00;Списание;Разовый расход;${tag};Разовый платёж;`];
    return Buffer.from(`\ufeff${lines.join("\n")}\n`);
  };
  // Первый новый снимок создаёт актуальный checkpoint даже на обновлённом старом стенде.
  const base = await upload(makeDelta(), 2);
  const updated = await upload(makeDelta(), 2);
  await expect(page.getByTestId("calculation-mode")).toContainText("новые факты учтены");
  expect(updated.id).not.toBe(base.id);
  expect(updated.calculation?.mode).toBe("incremental");
  expect(updated.calculation?.reason).toBe("observed_data_changed");
  expect(updated.calculation?.source_forecast_id).toBe(base.id);
  expect(updated.calculation?.categorized_transactions).toBe(2);
  expect(updated.calculation?.reused_transactions).toBeGreaterThan(0);
  expect(updated.calculation?.bootstrap_paths_generated).toBe(0);
  expect(updated.opening_balance_minor).toBe(base.opening_balance_minor);
  expect(await (await page.request.get(`/api/v1/forecasts/${initial.id}`)).json()).toEqual(initial);
  expect(await (await page.request.get(`/api/v1/forecasts/${base.id}`)).json()).toEqual(base);
});
