import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { expectObligationPreview, go, login, openObligations } from "./fixtures/app";

// Настоящий backend/worker: ошибки preview, сохранение плана, CSV и повтор после отмены.
test("manual plan and obligation CSV persist and feed a real forecast", async ({ page }) => {
  const tag = randomUUID();
  const today = new Date().toISOString().slice(0, 10);
  const due = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
  const counterparty = `Синтетический UI ${tag}`;
  const externalId = `ui-${tag}`;
  const csv = (direction: string) => Buffer.from(
    "\ufeffid;counterparty_ref;direction;amount;currency;due_date;available_at;kind;provenance\n"
    + `${externalId};demo-${tag};${direction};67.89;RUB;${due};${today};invoice;UI synthetic ${tag}\n`, "utf8");
  await login(page);
  await go(page, "Плановые платежи");
  await expect(page.getByRole("heading", { name: "Будущие платежи и обязательства", exact: true })).toBeVisible();
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("1,234");
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Введите сумму с точностью до копеек");
  await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("123,45");
  await page.getByLabel("Плановая дата", { exact: true }).fill(due);
  await page.getByLabel("Контрагент по плану", { exact: true }).fill(counterparty);
  await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
  const plans = page.getByRole("table", { name: "Плановые платежи", exact: true });
  const manual = plans.getByRole("row").filter({ hasText: counterparty });
  await expect(manual).toContainText("123,45");
  await go(page, "Прогноз");
  await expect(page.getByLabel("Дата среза", { exact: true })).toHaveValue(today);
  await openObligations(page);
  const file = page.getByLabel("CSV счетов и обязательств", { exact: true });
  await page.getByLabel("Источник обязательств", { exact: true }).fill("e2e-ui");
  await file.setInputFiles({ name: "invalid.csv", mimeType: "text/csv", buffer: csv("unknown") });
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expectObligationPreview(page, 1, 0, 1);
  await expect(page.getByRole("button", { name: "Подтвердить обязательства", exact: true })).toBeDisabled();
  await file.setInputFiles({ name: "valid.csv", mimeType: "text/csv", buffer: csv("out") });
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expectObligationPreview(page, 1, 1, 0);
  await page.getByRole("button", { name: "Подтвердить обязательства", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Обязательств добавлено:" })).toBeVisible();
  await go(page, "Плановые платежи");
  const imported = plans.getByRole("row").filter({ hasText: externalId });
  await expect(imported).toContainText("67,89");
  await expect(imported).toContainText(`UI synthetic ${tag}`);
  await go(page, "Прогноз");
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  await go(page, "Плановые платежи");
  await imported.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(imported).toContainText("Отменён");
  await manual.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(manual).toContainText("Отменён");
  await page.reload();
  await expect(page.getByRole("table", { name: "Плановые платежи", exact: true })
    .getByRole("row").filter({ hasText: externalId })).toContainText("Отменён");
  await openObligations(page);
  await file.setInputFiles({ name: "valid.csv", mimeType: "text/csv", buffer: csv("out") });
  await page.getByLabel("Источник обязательств", { exact: true }).fill("e2e-ui");
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expect(page.getByText(/Этот файл уже загружали/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить обязательства", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Обязательств добавлено:" })).toBeVisible();
  await go(page, "Плановые платежи");
  await expect(plans.getByRole("row").filter({ hasText: externalId })).toHaveCount(1);
  await expect(plans.getByRole("row").filter({ hasText: externalId })).toContainText("Отменён");
  await page.getByRole("button", { name: "Выйти (demo@example.com)", exact: true }).click();
});
