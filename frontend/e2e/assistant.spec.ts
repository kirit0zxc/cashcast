import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";

test("assistant CSV stays a preview until human confirmation; cancel and repeat are safe", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("demo@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("demo-password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByLabel("CSV-файл", { exact: true })).toBeVisible();
  const chat = page.getByRole("region", { name: "ИИ-ассистент CashCast" });
  await chat.getByText("Прикрепить CSV в чат", { exact: true }).click();
  const fixture = scenarioStatement();
  await chat.getByLabel("Файл для ассистента").setInputFiles({
    name: `chat-${randomUUID()}.csv`, mimeType: "text/csv", buffer: fixture.buffer,
  });
  const previewWait = page.waitForResponse(r => r.url().endsWith("/assistant/uploads"));
  await chat.getByRole("button", { name: "Проверить CSV в чате" }).click();
  const preview = await previewWait;
  expect(preview.status()).toBe(200);
  const body = await preview.json();
  const data = body.cards.find((c: { kind: string }) => c.kind === "action").data;
  const companyId = preview.url().split("/companies/")[1].split("/")[0];
  const transactionsUrl = `/api/v1/companies/${companyId}/transactions?account_id=${data.account_id}&limit=200`;
  const before = await (await page.request.get(transactionsUrl)).json();
  await expect(chat.getByTestId("assistant-action").first()).toContainText("Ожидает подтверждения");
  await chat.getByRole("button", { name: "Отменить предложение", exact: true }).first().click();
  await expect(chat.getByTestId("assistant-action").first()).toContainText("Отменено");
  expect(await (await page.request.get(transactionsUrl)).json()).toEqual(before);
  await chat.getByRole("button", { name: "Проверить CSV в чате" }).click();
  await expect(chat.getByRole("button", { name: "Подтвердить действие", exact: true })).toBeVisible();
  let forecastPosts = 0;
  page.on("request", r => { if (r.method() === "POST" && r.url().endsWith("/forecasts")) forecastPosts++; });
  await chat.getByRole("button", { name: "Подтвердить действие", exact: true }).click();
  await expect(chat.getByText("Действие подтверждено и принято сервером.", { exact: true })).toBeVisible();
  const after = await (await page.request.get(transactionsUrl)).json();
  expect(after.items.length).toBeGreaterThanOrEqual(fixture.rowCount);
  expect(forecastPosts).toBe(0); // Импорт в чате не разрешает новый платный/вычислительный шаг.
});
