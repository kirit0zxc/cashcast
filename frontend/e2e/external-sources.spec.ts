import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { go, login } from "./fixtures/app";

// Mock-поставщики, но настоящие API, PostgreSQL, worker и обновление прогноза.
test("demo bank, 1C and tax file feed plans once and update the forecast", async ({ page }) => {
  await login(page);
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const company = me.companies[0].id;
  const plans = async () => (await page.request.get(`/api/v1/companies/${company}/planned-events`)).json();
  const bankPlans = async () => (await plans()).filter((e: { source_ref: string | null }) =>
    e.source_ref?.includes(":external-demo-bank-v1:"));
  await go(page, "Импорт данных");
  await page.getByRole("tab", { name: "Банк, 1С и налоги", exact: true }).click();
  await expect(page.getByText(/Связи с банком, базой 1С и ФНС нет/)).toBeVisible();
  const before = (await bankPlans()).length;
  await page.getByRole("button", { name: "Получить демоданные банка", exact: true }).click();
  await expect(page.getByRole("table", { name: "Документы внешнего источника" })).toContainText("Зарплатный проект");
  expect((await bankPlans()).length).toBe(before);
  const add = page.getByRole("button", { name: "Добавить в план и обновить прогноз", exact: true });
  if (before === 0) {
    await add.click();
    await expect(page.getByRole("status").filter({ hasText: "Добавлено внешних платежей: 4" })).toBeVisible();
  } else {
    await expect(add).toBeDisabled();
  }
  expect((await bankPlans()).length).toBe(4);
  await page.getByRole("button", { name: "Получить демоданные банка", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Этот набор уже импортирован" })).toBeVisible();
  await expect(add).toBeDisabled();
  expect((await bankPlans()).length).toBe(4);
  await page.getByRole("button", { name: "Получить демоданные 1С", exact: true }).click();
  await expect(page.getByRole("table", { name: "Документы внешнего источника" })).toContainText("Договор №9");
  if (await add.isEnabled()) {
    await add.click();
    await expect(page.getByRole("status").filter({ hasText: "Добавлено внешних платежей: 4" })).toBeVisible();
  }
  const tag = randomUUID();
  const today = new Date().toISOString().slice(0, 10);
  const due = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
  const csv = (amount: string) => Buffer.from("\ufeffid;tax_name;amount;due_date;available_at;tax_regime;status\n"
    + `tax-${tag};ДЕМО Налог ${tag};${amount};${due};${today};УСН;due\n`
    + `paid-${tag};ДЕМО Оплачен;55.00;${due};${today};УСН;paid\n`, "utf8");
  const file = page.getByLabel("Демо-файл налоговых обязательств", { exact: true });
  await file.setInputFiles({ name: "invalid-taxes.csv", mimeType: "text/csv", buffer: csv("NaN") });
  await page.getByRole("button", { name: "Проверить налоговый файл", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Исправьте ошибки" })).toBeVisible();
  await expect(add).toBeDisabled();
  await file.setInputFiles({ name: "taxes.csv", mimeType: "text/csv", buffer: csv("123.45") });
  await page.getByRole("button", { name: "Проверить налоговый файл", exact: true }).click();
  await expect(page.getByTestId("external-preview")).toContainText(/Оплаченных и отменённых пропущено\s*1/);
  await add.click();
  await expect(page.getByRole("status").filter({ hasText: "Добавлено внешних платежей: 1" })).toBeVisible();
  const imported = (await plans()).filter((e: { source_ref: string | null }) => e.source_ref?.includes(tag));
  expect(imported).toHaveLength(1);
  expect(imported[0].amount_minor).toBe(12345);
  expect(imported[0].provenance).toContain("ДЕМО");
  await go(page, "Прогноз");
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  await go(page, "Плановые платежи");
  await expect(page.getByRole("table", { name: "Плановые платежи" })).toContainText(`ДЕМО Налог ${tag}`);
});
