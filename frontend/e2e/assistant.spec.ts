import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { scenarioStatement } from "./fixtures/scenario-statement";
import { go, goAssistant, login } from "./fixtures/app";

test("assistant CSV stays a preview until human confirmation; cancel and repeat are safe", async ({ page }) => {
  await login(page);
  await goAssistant(page);
  const chat = page.getByRole("region", { name: "ИИ-ассистент CashCast" });
  const fixture = scenarioStatement();
  const fileName = `chat-${randomUUID()}.csv`;
  // Незаконченный выбор файла не хранится между разделами — прикрепляем заново тот же CSV.
  async function attach() {
    await chat.getByText("Прикрепить CSV в чат", { exact: true }).click();
    await chat.getByLabel("Файл для ассистента").setInputFiles({ name: fileName, mimeType: "text/csv", buffer: fixture.buffer });
  }
  await attach();
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
  // Идентификаторы счёта не попадают в основной список параметров, только в «Технические параметры».
  await expect(chat.getByTestId("assistant-action").first().locator(":scope > dl")).not.toContainText(data.account_id);
  await chat.getByRole("button", { name: "Отменить предложение", exact: true }).first().click();
  await expect(chat.getByTestId("assistant-action").first()).toContainText("Отменено");
  // Чат того же счёта переживает переход в другой раздел и обратно.
  await go(page, "Обзор");
  await goAssistant(page);
  await expect(chat.getByTestId("assistant-action").first()).toContainText("Отменено");
  await expect(chat.getByTestId("assistant-action").first().getByRole("button")).toHaveCount(0);
  expect(await (await page.request.get(transactionsUrl)).json()).toEqual(before);
  await attach();
  await chat.getByRole("button", { name: "Проверить CSV в чате" }).click();
  await expect(chat.getByRole("button", { name: "Подтвердить действие", exact: true })).toBeVisible();
  let forecastPosts = 0;
  page.on("request", r => { if (r.method() === "POST" && r.url().endsWith("/forecasts")) forecastPosts++; });
  await chat.getByRole("button", { name: "Подтвердить действие", exact: true }).click();
  await expect(chat.getByText("Действие подтверждено и принято сервером.", { exact: true })).toBeVisible();
  const after = await (await page.request.get(transactionsUrl)).json();
  expect(after.items.length).toBeGreaterThanOrEqual(fixture.rowCount);
  expect(forecastPosts).toBe(0); // Импорт в чате не разрешает новый платный/вычислительный шаг.
  // Прогноз помечен устаревшим, но не пересчитан скрыто.
  await go(page, "Прогноз");
  await expect(page.getByText(/показанный прогноз устарел/)).toBeVisible();
  expect(forecastPosts).toBe(0);
});
