import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

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
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
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
  await expect(page.getByLabel("Дата среза", { exact: true })).toHaveValue(today);
  await page.getByText("Загрузить счета и обязательства из CSV", { exact: true }).click();
  const file = page.getByLabel("CSV счетов и обязательств", { exact: true });
  await page.getByLabel("Источник обязательств", { exact: true }).fill("e2e-ui");
  await file.setInputFiles({ name: "invalid.csv", mimeType: "text/csv", buffer: csv("unknown") });
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expect(page.getByText(/Обязательств проверено: 1\. Корректных: 0\. Ошибок: 1/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Подтвердить обязательства", exact: true })).toBeDisabled();
  await file.setInputFiles({ name: "valid.csv", mimeType: "text/csv", buffer: csv("out") });
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expect(page.getByText(/Обязательств проверено: 1\. Корректных: 1\. Ошибок: 0/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить обязательства", exact: true }).click();
  const imported = plans.getByRole("row").filter({ hasText: externalId });
  await expect(imported).toContainText("67,89");
  await expect(imported).toContainText(`UI synthetic ${tag}`);
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  await imported.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(imported).toContainText("Отменён");
  await manual.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(manual).toContainText("Отменён");
  await page.reload();
  await expect(page.getByRole("table", { name: "Плановые платежи", exact: true })
    .getByRole("row").filter({ hasText: externalId })).toContainText("Отменён");
  await page.getByText("Загрузить счета и обязательства из CSV", { exact: true }).click();
  await file.setInputFiles({ name: "valid.csv", mimeType: "text/csv", buffer: csv("out") });
  await page.getByLabel("Источник обязательств", { exact: true }).fill("e2e-ui");
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expect(page.getByText(/Этот файл уже загружали/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить обязательства", exact: true }).click();
  await expect(plans.getByRole("row").filter({ hasText: externalId })).toHaveCount(1);
  await expect(plans.getByRole("row").filter({ hasText: externalId })).toContainText("Отменён");
  await page.getByRole("button", { name: "Выйти (demo@example.com)", exact: true }).click();
});
