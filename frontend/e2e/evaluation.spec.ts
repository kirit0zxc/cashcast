import { expect, test } from "@playwright/test";
import { login } from "./fixtures/app";

test("контрольный набор: реальная очередь, метрики, график, журнал и автономный отчёт", async ({ page }) => {
  await login(page);
  await page.getByRole("combobox", { name: "Счёт", exact: true }).selectOption({ label: "Расчётный счёт · RUB" });
  const companyId = await page.getByRole("combobox", { name: "Компания", exact: true }).inputValue();
  const accountId = await page.getByRole("combobox", { name: "Счёт", exact: true }).inputValue();
  // Отдельная база Compose: импортируем синтетику через настоящий API, без MSW.
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  // Стабильные банковские ID позволяют повторить тест без удвоения расходов.
  const unique = "checkpoint-evaluation-v1";
  const start = Date.parse("2024-01-01");
  let balance = 1000;
  const rows = ["date,amount,id,balance,purpose"];
  for (let i = 0; i < 110; i++) {
    balance -= 13;
    const day = new Date(start + i * 86400000).toISOString().slice(0, 10);
    rows.push(`${day},-13,${unique}-${i},${balance},SYNTHETIC_SECRET_MARKER`);
  }
  const imported = await page.request.post(`/api/v1/companies/${companyId}/imports`, {
    headers: { "X-CSRF-Token": me.csrf_token }, multipart: {
      account_id: accountId,
      mapping: JSON.stringify({ date: "date", amount: "amount", external_id: "id", balance: "balance", purpose: "purpose" }),
      file: { name: "checkpoint.csv", mimeType: "text/csv", buffer: Buffer.from(rows.join("\n")) },
    },
  });
  expect(imported.status(), await imported.text()).toBe(200);
  const preview = await imported.json();
  expect(preview.error_count).toBe(0);
  expect((await page.request.post(`/api/v1/imports/${preview.import_id}/commit`, {
    headers: { "X-CSRF-Token": me.csrf_token },
  })).status()).toBe(200);
  await page.getByRole("navigation", { name: "Разделы", exact: true })
    .getByRole("link", { name: /Проверка качества$/ }).click();
  await page.getByLabel("Первая дата среза", { exact: true }).fill("2024-03-10");
  await page.getByLabel("Горизонт, дней", { exact: true }).fill("10");
  await page.getByLabel("Последовательных окон", { exact: true }).fill("3");
  await page.getByRole("checkbox").check();
  const acceptedResponse = page.waitForResponse(r => r.url().endsWith("/evaluations") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Проверить качество", exact: true }).click();
  const accepted = await acceptedResponse;
  expect(accepted.status()).toBe(202);
  const { id } = await accepted.json();
  const panel = page.getByTestId("evaluation-report");
  await expect(panel).toBeVisible({ timeout: 45000 });
  await expect(panel).toContainText("seasonal-damped-2.2-w84");
  await expect(panel).toContainText("Пошаговый журнал вычислений");
  await expect(panel).toContainText("ROC-AUC");
  await expect(panel.getByRole("img", { name: "График прогноза и фактического остатка" })).toHaveCount(3);
  const response = await page.request.get(`/api/v1/evaluations/${id}`);
  const report = (await response.json()).report;
  expect(report.regression.balance.n).toBe(30);
  expect(report.daily_median_negative.n).toBe(30);
  expect(report.daily_median_negative.confusion_matrix.tp).toBeGreaterThan(0);
  expect(JSON.stringify(report)).not.toContain("SYNTHETIC_SECRET_MARKER");
  const download = page.waitForEvent("download");
  await panel.getByRole("link", { name: "Скачать HTML с графиками" }).click();
  expect((await download).suggestedFilename()).toContain(id);
  const html = await page.request.get(`/api/v1/evaluations/${id}/report?format=html`);
  expect(await html.text()).toContain("<svg");
  await page.screenshot({ path: "test-results/checkpoint-evaluation.png", fullPage: true });
  await page.reload();
  await page.getByText("Последние сохранённые проверки", { exact: true }).click();
  await page.getByRole("button", { name: new RegExp(`${id}.*succeeded`) }).click();
  await expect(page.getByTestId("evaluation-report")).toBeVisible();
});
