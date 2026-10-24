import { expect, test, type Page } from "@playwright/test";

// Фиксируем редкие ответы API; расчёты сервера проверяются отдельно backend-тестами.
// Здесь проверяем, что интерфейс не меняет смысл watch, условного риска и временных сумм.
async function fixture(page: Page, cash: Record<string, unknown> = {}) {
  const forecast = { id: "forecast", status: "succeeded", base_forecast_id: null,
    as_of: "2026-10-01", model_version: "seasonal-estimated-2.1-w84", data_version: "fixture",
    opening_balance_minor: -100000, assumptions: [], data_warnings: [],
    risk: { available: false, probability_any_negative: null, first_negative_date: null, max_deficit_minor: null },
    points: [{ point_date: "2026-10-02", inflow_minor: 0, outflow_minor: 9900000,
      balance_p10_minor: -10000000, balance_p50_minor: -10000000, balance_p90_minor: -10000000,
      probability_negative: null }] };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    let body: unknown;
    if (path === "/auth/me") body = { id: "user", email: "demo@example.com", csrf_token: "fixture",
      companies: [{ id: "company", name: "Синтетическое демо", role: "owner" }] };
    else if (path === "/auth/logout") return route.fulfill({ status: 204 });
    else if (path.endsWith("/accounts")) body = { items: [{ id: "account", name: "Демо", currency: "RUB" }] };
    else if (path === "/companies/company/forecasts") body = { items: [forecast], next_cursor: null };
    else if (path === "/forecasts/forecast") body = forecast;
    else if (path.endsWith("/planned-events")) body = [];
    else if (path.endsWith("/plan-fact")) body = { proposals: [] };
    else if (path.endsWith("/cash-gaps")) body = { forecast_id: "forecast", as_of: "2026-10-01", horizon_end: "2026-10-02",
      base: { status: "gap", opening_already_negative: true, first_new_gap_date: null,
        max_deficit_minor: 10000000, required_reserve_minor: 10000000, episodes: [] },
      probability: null, points: [{ date: "2026-10-01", base_minor: -100000 }, { date: "2026-10-02", base_minor: -10000000 }] };
    else if (path.endsWith("/pulse")) body = { forecast_id: "forecast", status: "watch", headline: "Тестовая оценка",
      actions: [], warnings: [], model_version: "fixture", data_version: "fixture", method_version: "fixture",
      cash: { status: "watch", message: "Остаток опустится ниже безопасного запаса 800 ₽ 02.10.",
        first_gap_date: null, buffer_minor: 80000, buffer_source: "user", plan: null, suggestions: [],
        assumptions: [], warnings: [], structural_shortfall: false, gap_only_if_owner_withdraws: false,
        chart: { days: ["2026-10-02"], base_minor: [50000], if_owner_withdraws_minor: null,
          after_plan_minor: null, buffer_minor: 80000 }, ...cash },
      money: { status: "ok", assumptions: [] }, clients: { status: "ok", applicable: false } };
    else return route.fulfill({ status: 404, json: { error: { code: "fixture", message: "Нет тестового ответа" } } });
    await route.fulfill({ json: body });
  });
}

test("подушка: положительный остаток ниже резерва остаётся предупреждением", async ({ page }) => {
  await fixture(page);
  await page.goto("/pulse");
  const verdict = page.locator(".cushion-verdict");
  await expect(verdict).toContainText("ниже безопасного запаса 800 ₽");
  await expect(verdict).toHaveClass(/tone-watch/);
  await expect(verdict).not.toContainText("Запаса хватает");
});

test("подушка сохраняет условие вывода денег владельцем", async ({ page }) => {
  await fixture(page, { status: "risk", first_gap_date: "2026-10-02", gap_only_if_owner_withdraws: true,
    message: "Возможная нехватка денег 02.10 — если выводить деньги из бизнеса как обычно.",
    chart: { days: ["2026-10-02"], base_minor: [100000], if_owner_withdraws_minor: [-20000],
      after_plan_minor: null, buffer_minor: 80000 } });
  await page.goto("/pulse");
  await expect(page.locator(".cushion-verdict")).toContainText("если выводить деньги из бизнеса как обычно");
});

test("подушка не превращает unknown в обещание достаточности", async ({ page }) => {
  await fixture(page, { status: "unknown", message: "Недостаточно данных для прогноза остатка." });
  await page.goto("/pulse");
  await expect(page.locator(".cushion-verdict")).toContainText("оценка недоступна");
  await expect(page.locator(".cushion-verdict")).toHaveClass(/tone-unknown/);
});

test("сумма будущего максимума не выдаётся за сумму на дату среза", async ({ page }) => {
  await fixture(page);
  await page.goto("/overview");
  const banner = page.getByRole("region", { name: "Кассовый разрыв", exact: true });
  await expect(banner.locator("b")).toContainText("На дату среза");
  await expect(banner.locator("b")).not.toContainText("100");
  await expect(banner).toContainText("Максимальная нехватка за период");
  await expect(banner.locator("strong").first()).toContainText(/100\s*000,00/);
});

test("короткий экран: выход доступен прокруткой бокового меню", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  await fixture(page);
  await page.goto("/overview");
  const logout = page.getByRole("button", { name: /Выйти/ });
  await expect(logout).toBeVisible();
  await page.locator(".side").hover();
  await page.mouse.wheel(0, 1200);
  await expect.poll(async () => page.evaluate(() => {
    const side = document.querySelector(".side")!.getBoundingClientRect();
    const button = document.querySelector(".side .user button")!.getBoundingClientRect();
    return button.bottom <= side.bottom && button.top >= side.top;
  })).toBe(true);
  const reply = page.waitForResponse(r => r.url().endsWith("/auth/logout"));
  await logout.click();
  expect((await reply).status()).toBe(204);
  await expect(page.getByRole("button", { name: "Войти", exact: true })).toBeVisible();
});
