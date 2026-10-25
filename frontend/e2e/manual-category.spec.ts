import { expect, test } from "@playwright/test";
import { expectStatementPreview, go } from "./fixtures/app";

test("manual category survives reload/reimport and does not rewrite a saved forecast", async ({ page }) => {
  // Отдельная старая операция без остатка не перезаписывает банковскую историю других тестов.
  const csv = Buffer.from("\ufeffoperation_id;operation_date;amount;direction;counterparty_name;payment_purpose\n"
    + "category-ui-fixed;2024-01-02;12.34;Списание;Проверка ручной категории;Синтетическая операция\n");
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  async function importFile() {
    await go(page, "Импорт данных");
    await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
      name: "category.csv", mimeType: "text/csv", buffer: csv,
    });
    await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
    await expectStatementPreview(page, 1);
    await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Добавлено:" })).toBeVisible();
  }
  await importFile();
  await go(page, "Операции");
  const table = page.getByRole("table", { name: "Банковские операции", exact: true });
  const row = table.getByRole("row").filter({ hasText: "Проверка ручной категории" });
  await expect(row).toBeVisible();
  await go(page, "Прогноз");
  const response = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  const baseId = (await (await response).json()).forecast_run_id as string;
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  const original = await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json();
  await go(page, "Операции");
  // При повторе меняем значение, а не подтверждаем уже сохранённые fees.
  const wasFees = (await row.getByTestId("transaction-category").innerText()) === "Комиссии";
  const category = wasFees ? "tax" : "fees";
  const label = wasFees ? "Налоги" : "Комиссии";
  await row.getByText("Изменить категорию", { exact: true }).click();
  await row.getByRole("combobox", { name: "Новая категория", exact: true }).selectOption(category);
  const saved = page.waitForResponse(r => r.url().endsWith("/category") && r.request().method() === "PATCH");
  const refreshed = page.waitForResponse(r => r.url().endsWith("/forecasts") && r.request().method() === "POST");
  await row.getByRole("button", { name: "Сохранить категорию", exact: true }).click();
  const transaction = await (await saved).json();
  expect(transaction.category).toBe(category);
  expect(transaction.category_source).toBe("manual");
  await expect(row).toContainText("Выбрано вами");
  await expect(row.getByRole("status")).toContainText("автоматически");
  const next = await (await refreshed).json();
  expect(next.forecast_run_id).not.toBe(baseId);
  await go(page, "Прогноз");
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  expect(await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json()).toEqual(original);
  await page.reload();
  await go(page, "Операции");
  await expect(row).toContainText("Выбрано вами");
  await expect(row.getByTestId("transaction-category")).toHaveText(label);
  await importFile();
  await go(page, "Операции");
  await expect(row).toContainText("Выбрано вами");
  await expect(row.getByTestId("transaction-category")).toHaveText(label);
  expect(await (await page.request.get(`/api/v1/forecasts/${baseId}`)).json()).toEqual(original);
});
