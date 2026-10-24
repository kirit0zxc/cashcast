import { expect, test } from "@playwright/test";

// Файл строится в памяти и безопасен для повторного запуска: импорт идемпотентен.
function statement() {
  const rows = ["operation_id;operation_date;amount;direction;counterparty_name;counterparty_inn;payment_purpose;balance_eod"];
  for (let day = 1; day <= 14; day++) {
    const date = `2026-08-${String(day).padStart(2, "0")}`;
    rows.push(`e2e-${day};${date};100.00;Поступление;Тестовый клиент;00123;Синтетическая оплата;${1000 + day * 100}.00`);
  }
  return Buffer.from(`\ufeff${rows.join("\n")}\n`, "utf8");
}

test("login → account → preview/commit → worker forecast → logout", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Неверный email или пароль");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Счёт", exact: true })).toContainText("Расчётный счёт");
  await page.getByLabel("CSV-файл").setInputFiles({ name: "e2e.csv", mimeType: "text/csv", buffer: statement() });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expect(page.getByText(/Строк: 14\. Ошибок: 0/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Добавлено:" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Результат сохранённого импорта." })).toBeVisible();
  await expect(page.getByText("При повторном подтверждении возвращается та же сводка; операции заново не добавляются.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Дата среза", { exact: true })).toHaveValue("2026-08-14");
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  await page.getByText("Дневные значения и происхождение расчёта", { exact: true }).click();
  await expect(page.getByRole("cell", { name: "2026-09-13", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Причины риска и компоненты", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Вид сценария", exact: true }).selectOption("delay_event");
  await expect(page.getByRole("button", { name: "Проверить сценарий", exact: true })).toBeDisabled();
  await expect(page.getByText("В сохранённой базе нет будущего поступления. Добавьте план и пересчитайте базу.")).toBeVisible();
  await page.getByRole("combobox", { name: "Вид сценария", exact: true }).selectOption("add_expense");
  await page.getByLabel("Дополнительный расход, ₽", { exact: true }).fill("1234,56");
  await page.getByRole("button", { name: "Проверить сценарий", exact: true }).click();
  await expect(page.getByTestId("scenario-comparison")).toContainText("1 234,56");
  await page.getByRole("button", { name: "Выйти (demo@example.com)", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Вход", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Вход", exact: true })).toBeVisible();
});
