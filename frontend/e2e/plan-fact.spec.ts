import { expect, test, type Page } from "@playwright/test";
import { scenarioStatement } from "./fixtures/scenario-statement";

async function loginAndImport(page: Page) {
  const { today, rowCount, buffer } = scenarioStatement();
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({ name: "scenarios.csv", mimeType: "text/csv", buffer });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expect(page.getByText(new RegExp(`Строк: ${rowCount}\\. Ошибок: 0`))).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Добавлено:" })).toBeVisible();
  return today;
}

// Стабильный исходный документ повторно не присваивает уже распределённую операцию.
test("read-only plan-fact becomes a stored payment only after explicit auto reconcile", async ({ page }) => {
  const today = await loginAndImport(page);
  const sourceId = `e2e-pf-${today}`;
  await page.getByText("Загрузить счета и обязательства из CSV", { exact: true }).click();
  await page.getByLabel("Источник обязательств", { exact: true }).fill("e2e-plan-fact");
  await page.getByLabel("CSV счетов и обязательств", { exact: true }).setInputFiles({
    name: "plan-fact.csv", mimeType: "text/csv", buffer: Buffer.from(
      "id;counterparty_ref;direction;amount;currency;due_date;available_at;kind;provenance\n"
      + `${sourceId};e2e-scenario-revenue;in;50.00;RUB;${today};${today};invoice;E2E synthetic\n`),
  });
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expect(page.getByText(/Обязательств проверено: 1\. Корректных: 1\. Ошибок: 0/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить обязательства", exact: true }).click();
  const row = page.getByRole("table", { name: "План и связанные оплаты", exact: true })
    .getByRole("row").filter({ hasText: sourceId });
  await expect(row).toBeVisible();
  const account = await page.getByRole("combobox", { name: "Счёт", exact: true }).inputValue();
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const path = `/api/v1/companies/${me.companies[0].id}/plan-fact?account_id=${account}&as_of=${today}`;
  const before = await (await page.request.get(path)).json();
  const event = before.items.find((item: { event: { source_ref: string | null } }) => item.event.source_ref?.endsWith(sourceId)).event;
  const paid = before.confirmed_matches.filter((match: { planned_event_id: string }) => match.planned_event_id === event.id);
  if (paid.length === 0) {
    // Два GET не подтверждают предложение; кнопка вызывает единственный изменяющий POST.
    const again = await (await page.request.get(path)).json();
    expect(again.confirmed_matches.filter((match: { planned_event_id: string }) => match.planned_event_id === event.id)).toHaveLength(0);
    expect(before.proposals.some((proposal: { planned_event_id: string; auto_confirm: boolean }) =>
      proposal.planned_event_id === event.id && proposal.auto_confirm)).toBe(true);
    await expect(row.getByRole("cell").nth(3)).toContainText("0,00");
    await page.getByRole("button", { name: "Применить однозначные совпадения", exact: true }).click();
  }
  await expect(row).toContainText("Оплачен");
  await expect(row.getByRole("cell").nth(3)).toContainText("50,00");
  const after = await (await page.request.get(path)).json();
  const matches = after.confirmed_matches.filter((match: { planned_event_id: string }) => match.planned_event_id === event.id);
  expect(matches).toHaveLength(1);
  expect(matches[0].matched_amount_minor).toBe(5000);
  await page.reload();
  await expect(page.getByRole("table", { name: "План и связанные оплаты", exact: true }).getByRole("row")
    .filter({ hasText: sourceId })).toContainText("Оплачен");
});

test("today forecast refreshes reconciled plans without losing its pending job", async ({ page }) => {
  const today = await loginAndImport(page);
  const dayIndex = Date.parse(today) / 86400000;
  const rentIndex = dayIndex - ((dayIndex - 1) % 7 + 7) % 7;
  const paidOn = new Date(rentIndex * 86400000).toISOString().slice(0, 10);
  const sourceId = `e2e-forecast-auto-${paidOn}`;
  await page.getByText("Загрузить счета и обязательства из CSV", { exact: true }).click();
  await page.getByLabel("Источник обязательств", { exact: true }).fill("e2e-forecast-auto");
  await page.getByLabel("CSV счетов и обязательств", { exact: true }).setInputFiles({
    name: "forecast-auto.csv", mimeType: "text/csv", buffer: Buffer.from(
      "id;counterparty_ref;direction;amount;currency;due_date;available_at;kind;provenance\n"
      + `${sourceId};e2e-scenario-rent;out;77.77;RUB;${paidOn};${paidOn};invoice;E2E synthetic\n`),
  });
  await page.getByRole("button", { name: "Проверить обязательства", exact: true }).click();
  await expect(page.getByText(/Обязательств проверено: 1\. Корректных: 1\. Ошибок: 0/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить обязательства", exact: true }).click();
  const plans = page.getByRole("table", { name: "Плановые платежи", exact: true })
    .getByRole("row").filter({ hasText: sourceId });
  const linked = page.getByRole("table", { name: "План и связанные оплаты", exact: true })
    .getByRole("row").filter({ hasText: sourceId });
  await expect(linked).toBeVisible();
  await expect(page.getByLabel("Дата среза", { exact: true })).toHaveValue(today);
  await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
  await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
  await expect(linked).toContainText("Оплачен");
  await expect(linked.getByRole("cell").nth(3)).toContainText("77,77");
  await expect(plans).toContainText("Оплачен");
  // Ни reload, ни ручная кнопка сверки не потребовались; job дошёл до графика.
});
