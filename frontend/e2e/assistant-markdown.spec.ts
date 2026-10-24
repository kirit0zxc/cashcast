import { expect, test } from "@playwright/test";
import { goAssistant, login } from "./fixtures/app";

test("assistant renders markdown while user text and untrusted HTML stay inert", async ({ page }) => {
  // Только ответ модели детерминирован; вход и кабинет используют настоящий сервер.
  await page.route("**/api/v1/assistant/status", route => route.fulfill({ json: { enabled: true, model: "test" } }));
  await page.route("**/api/v1/companies/*/assistant/chat", route => route.fulfill({ json: {
    text: "## Проверка\n\n**Итог**: 123,45 ₽\n\n- Первый\n- Второй\n\n| Статья | Сумма |\n|---|---:|\n| Закупка | 123,45 ₽ |\n\n```text\n<не HTML>\n```\n\n[Справка](https://example.com/docs)\n\n<script>window.alert('xss')</script>\n\n![pixel](https://tracker.test/pixel)\n\n[опасно](javascript:alert%281%29)",
    cards: [], error_code: null,
  } }));
  const tracking: string[] = [];
  page.on("request", request => { if (request.url().includes("tracker.test")) tracking.push(request.url()); });
  await login(page);
  await goAssistant(page);
  const chat = page.getByRole("region", { name: "ИИ-ассистент CashCast" });
  await chat.getByLabel("Сообщение ассистенту").fill("**Мой текст**");
  await chat.getByRole("button", { name: "Отправить ассистенту", exact: true }).click();
  const rendered = chat.locator(".assistant-markdown");
  await expect(rendered.getByRole("heading", { name: "Проверка" })).toBeVisible();
  await expect(rendered.locator("strong")).toHaveText("Итог");
  await expect(rendered.getByRole("listitem")).toHaveCount(2);
  await expect(rendered.getByRole("cell", { name: "123,45 ₽" })).toBeVisible();
  await expect(rendered.locator("pre code")).toHaveText("<не HTML>\n");
  await expect(rendered.getByRole("link", { name: "Справка" })).toHaveAttribute("rel", "noopener noreferrer");
  await expect(rendered.locator("script, img")).toHaveCount(0);
  await expect(rendered.getByRole("link", { name: "опасно" })).toHaveCount(0);
  await expect(chat.locator(".assistant-message.user")).toContainText("**Мой текст**");
  await expect(chat.locator(".assistant-message.user strong")).toHaveCount(0);
  expect(tracking).toEqual([]);
});
