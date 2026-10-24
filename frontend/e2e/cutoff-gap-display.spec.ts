import { expect, test } from "@playwright/test";
import type { Forecast } from "../src/shared/api";
import { go } from "./fixtures/app";

// UI-регрессия на фиксированных ответах API; математический пример проверяется Python-тестом.
for (const negative of [false, true]) {
  test(`cutoff median summary is independent of probability: negative=${negative}`, async ({ page }) => {
    let selected = "positive";
    let posts = 0;
    const forecast = (id: string): Forecast => ({
      id, status: "succeeded", base_forecast_id: null, as_of: id === "positive" ? "2026-08-01" : "2026-08-02",
      model_version: "seasonal-estimated-2.1-w84", data_version: id, opening_balance_minor: 26040000,
      assumptions: [], data_warnings: ["Менее 28 дней пригодной истории."],
      risk: { available: false, first_negative_date: null, max_deficit_minor: null, probability_any_negative: null },
      points: Array.from({ length: 30 }, (_, i) => {
        const balance = id === "changed" && negative && i >= 1 ? -50000 : 24790000;
        return { point_date: new Date(Date.parse(id === "positive" ? "2026-08-02" : "2026-08-03") + i * 86400000)
          .toISOString().slice(0, 10), inflow_minor: 0, outflow_minor: 0,
        balance_p10_minor: balance, balance_p50_minor: balance, balance_p90_minor: balance, probability_negative: null };
      }),
    });
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      let body: unknown;
      if (path === "/auth/me") body = { id: "user", email: "demo@example.com", csrf_token: "test",
        companies: [{ id: "company", name: "Синтетическое демо", role: "owner" }] };
      else if (path.endsWith("/accounts")) body = { items: [{ id: "account", name: "Демо", currency: "RUB" }] };
      else if (path === "/companies/company/forecasts" && route.request().method() === "POST") {
        expect(route.request().postDataJSON().as_of).toBe("2026-08-02");
        posts++; selected = "changed"; body = { forecast_run_id: selected, job_id: "job" };
      } else if (path === "/companies/company/forecasts") body = { items: [forecast(selected)], next_cursor: null };
      else if (path === "/jobs/job") body = { id: "job", status: "succeeded", error_code: null };
      else if (/^\/forecasts\/[^/]+$/.test(path)) body = forecast(path.split("/")[2]);
      else if (path.endsWith("/pulse")) body = { status: negative && selected === "changed" ? "risk" : "unknown",
        headline: "Недостаточно пригодной истории.", cash: { message: "Проверка медианы" }, actions: [] };
      else if (path.endsWith("/planned-events")) body = [];
      else if (path.endsWith("/plan-fact")) body = { proposals: [] };
      else if (path.endsWith("/explanations")) body = { available: false, summary: "Демо", items: [] };
      else return route.fulfill({ status: 404, json: { error: { code: "fixture", message: "Нет тестового ответа" } } });
      await route.fulfill({ status: route.request().method() === "POST" ? 202 : 200, json: body });
    });
    await page.goto("/forecast");
    await expect(page.getByText("не выявлен по медиане", { exact: true })).toBeVisible();
    await expect(page.getByTestId("probability-notice")).toContainText("это не 0%");
    await page.getByLabel("Дата среза", { exact: true }).fill("2026-08-02");
    await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toHaveCount(0);
    expect(posts).toBe(0);
    await page.getByRole("button", { name: "Рассчитать", exact: true }).click();
    await expect(page.getByRole("img", { name: "Прогноз остатка: p10, медиана, p90", exact: true })).toBeVisible();
    const deficit = page.locator(".leaders > div").filter({ hasText: "Максимальный дефицит по медиане" });
    await expect(deficit).toContainText(negative ? "500,00" : "0,00");
    await go(page, "Обзор");
    await expect(page.getByLabel("Статус финансового пульса")).toContainText(negative ? "Есть риск" : "Недостаточно данных");
    await expect(page.getByText("Список на сегодня.", { exact: false })).toContainText("планы, известные на 2 авг");
    if (negative) await expect(page.getByText("Возможный минус с 4 авг", { exact: true })).toBeVisible();
    else await expect(page.getByText("не выявлен по медиане", { exact: true })).toBeVisible();
    expect(posts).toBe(1);
  });
}
