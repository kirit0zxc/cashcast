import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("ambiguous payment is reviewed and split manually without double allocation", async ({ page }) => {
  const tag = randomUUID();
  const today = new Date().toISOString().slice(0, 10);
  const name = `Ручная сверка ${tag}`;
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByLabel("CSV-файл", { exact: true }).setInputFiles({
    name: "manual-payment.csv", mimeType: "text/csv", buffer: Buffer.from(
      "\ufeffoperation_id;operation_date;amount;direction;counterparty_name;payment_purpose\n"
      + `${tag};${today};98.76;Списание;${name};Синтетическая ручная оплата\n`
      // Нулевое суммарное движение не ломает остатки общей банковской fixture.
      + `${tag}-in;${today};98.76;Поступление;Пополнение ${tag};Синтетическое пополнение\n`),
  });
  await page.getByRole("button", { name: "Проверить файл", exact: true }).click();
  await expect(page.getByText(/Строк: 2\. Ошибок: 0/)).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить импорт", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Добавлено:" })).toBeVisible();
  const events: string[] = [];
  for (let index = 0; index < 2; index++) {
    await page.getByRole("combobox", { name: "Движение по плану", exact: true }).selectOption("out");
    await page.getByLabel("Планируемая сумма, ₽", { exact: true }).fill("98,76");
    await page.getByLabel("Плановая дата", { exact: true }).fill(today);
    await page.getByLabel("Контрагент по плану", { exact: true }).fill(name);
    const created = page.waitForResponse(r => r.url().endsWith("/planned-events") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Добавить платёж", exact: true }).click();
    events.push((await (await created).json()).id);
    await expect(page.getByRole("table", { name: "Плановые платежи", exact: true }).getByRole("row")
      .filter({ hasText: name })).toHaveCount(index + 1);
  }
  const companyId = await page.getByRole("combobox", { name: "Компания", exact: true }).inputValue();
  const accountId = await page.getByRole("combobox", { name: "Счёт", exact: true }).inputValue();
  const path = `/api/v1/companies/${companyId}/plan-fact?account_id=${accountId}&as_of=${today}`;
  const before = await (await page.request.get(path)).json();
  const proposal = before.proposals.find((item: { planned_event_id: string }) => item.planned_event_id === events[0]);
  expect(proposal.auto_confirm).toBe(false);
  await page.getByText("Предложения и подтверждённые связи", { exact: true }).click();
  for (const [index, amount, expectedMinor] of [[0, "40,00", 4000], [1, "58,76", 5876]] as const) {
    const choice = page.getByTestId(`proposal-${events[index]}-${proposal.transaction_id}`);
    await choice.getByRole("button", { name: "Проверить предложение", exact: true }).click();
    await expect(choice.getByText("Назначение: Синтетическая ручная оплата.", { exact: true })).toBeVisible();
    await choice.getByLabel("Подтверждаемая сумма, ₽", { exact: true }).fill(amount);
    const confirmed = page.waitForResponse(r => r.url().endsWith("/plan-fact/confirm") && r.request().method() === "POST");
    await choice.getByRole("button", { name: "Подтвердить выбранную оплату", exact: true }).click();
    const response = await confirmed;
    expect(response.status()).toBe(200);
    expect((await response.json()).confirmed_matches.find((item: { planned_event_id: string }) =>
      item.planned_event_id === events[index]).matched_amount_minor).toBe(expectedMinor);
    await expect(choice).toHaveCount(0);
  }
  await page.reload();
  const after = await (await page.request.get(path)).json();
  const links = after.confirmed_matches.filter((item: { transaction_id: string }) => item.transaction_id === proposal.transaction_id);
  expect(links).toHaveLength(2);
  expect(links.reduce((sum: number, item: { matched_amount_minor: number }) => sum + item.matched_amount_minor, 0)).toBe(9876);
  const user = await (await page.request.get("/api/v1/auth/me")).json();
  const retry = await page.request.post(`/api/v1/companies/${companyId}/plan-fact/confirm`, {
    headers: { "X-CSRF-Token": user.csrf_token }, data: { account_id: accountId, planned_event_id: events[0],
      transaction_id: proposal.transaction_id, matched_amount_minor: 4000 },
  });
  expect(retry.status()).toBe(200);
  const planRows = page.getByRole("table", { name: "Плановые платежи", exact: true }).getByRole("row").filter({ hasText: name });
  await expect(planRows).toHaveCount(2);
  await expect(planRows.first()).toContainText("Частично");
  // Не оставляем синтетические обязательства открытыми для следующих расчётов.
  await planRows.first().getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(planRows.first()).toContainText("Отменён");
  await planRows.nth(1).getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(planRows.nth(1)).toContainText("Отменён");
});
