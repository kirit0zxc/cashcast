import { expect, type Page } from "@playwright/test";

// Общие шаги E2E для кабинета с разделами. Переход — клик по меню (клиентский маршрут),
// поэтому выбранный расчёт и job сохраняются между разделами, как у пользователя.
export type Section = "Обзор" | "Операции" | "Импорт данных" | "Плановые платежи" | "Сверка оплат"
  | "Прогноз" | "Сценарии" | "Финансовый пульс";

export async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Разделы", exact: true })).toBeVisible();
}

export async function go(page: Page, section: Section) {
  const link = page.getByRole("navigation", { name: "Разделы", exact: true })
    .getByRole("link", { name: new RegExp(`${section}$`) });
  await link.click();
  await expect(link).toHaveAttribute("aria-current", "page");
}

// Итог проверки выписки: строки «Строк в файле … N», «Ошибок … 0».
export async function expectStatementPreview(page: Page, rows: number) {
  await expect(page.getByTestId("statement-preview"))
    .toContainText(new RegExp(`Строк в файле\\s*${rows}\\s*Ошибок\\s*0(?!\\d)`));
}

export async function openObligations(page: Page) {
  await go(page, "Импорт данных");
  await page.getByRole("tab", { name: "Счета и обязательства", exact: true }).click();
}

export async function expectObligationPreview(page: Page, total: number, valid: number, errors: number) {
  await expect(page.getByTestId("obligation-preview")).toContainText(new RegExp(
    `Обязательств в файле\\s*${total}\\s*Корректных\\s*${valid}\\s*Ошибок\\s*${errors}(?!\\d)`));
}

// Импорт выписки через вкладку «Банковская выписка»: файл → проверка → подтверждение.
export async function importStatement(page: Page, file: { name: string; buffer: Buffer }, rows: number) {
  await go(page, "Импорт данных");
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({ name: file.name, mimeType: "text/csv", buffer: file.buffer });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expectStatementPreview(page, rows);
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Добавлено:" })).toBeVisible();
}
