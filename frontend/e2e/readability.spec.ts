import { expect, test } from "@playwright/test";
import { go, goAssistant } from "./fixtures/app";

// Синтетические данные: одинаковые даты/суммы и общий префикс ID специально проверяют неоднозначность.
const ids = ["11111111-0000-4000-8000-000000000001", "11111111-0000-4000-8000-000000000002"];
const points = Array.from({ length: 90 }, (_, i) => ({
  point_date: new Date(Date.UTC(2026, 0, 2 + i)).toISOString().slice(0, 10),
  inflow_minor: 1000, outflow_minor: 900, balance_p10_minor: -1000,
  balance_p50_minor: 10000 + i, balance_p90_minor: 20000, probability_negative: 0.1,
}));
const risk = { available: false, first_negative_date: null, max_deficit_minor: null,
  probability_any_negative: 0.2, probability_status: "estimated_uncalibrated", probability_calibrated: false };
const forecast = { id: "forecast", as_of: "2026-01-01", status: "succeeded", base_forecast_id: null,
  model_version: "fixture", data_version: "fixture", opening_balance_minor: 10000,
  assumptions: [], data_warnings: [], points, risk };

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    let body: unknown;
    if (path === "/auth/me") body = { id: "user", email: "fixture@example.test", csrf_token: "fixture",
      companies: [{ id: "company", name: "Тестовая компания", role: "owner" }] };
    else if (path === "/companies/company/accounts") body = { items: [{ id: "account", name: "Тестовый счёт", currency: "RUB" }] };
    else if (path === "/companies/company/forecasts") body = { items: [{ ...forecast, horizon_days: 90 }], next_cursor: null };
    else if (path === "/forecasts/forecast") body = forecast;
    else if (path.endsWith("/explanations")) body = { available: true, items: ids.map(source_ref => ({
      kind: "planned", label: "Ожидаемое поступление", amount_minor: 12345, source_ref,
      detail: { date: "2026-01-10", direction: "in" },
    })) };
    else if (path.endsWith("/scenarios")) body = { job_id: "job", forecast_run_id: "scenario", status: "pending" };
    else if (path === "/jobs/job") body = { id: "job", status: "succeeded", error_code: null };
    else if (path.endsWith("/comparison")) body = { base_forecast_id: "forecast", scenario_forecast_id: "scenario",
      risk: { base: risk, scenario: risk }, points: points.map(p => ({ point_date: p.point_date,
        base_balance_p50_minor: p.balance_p50_minor, scenario_balance_p50_minor: p.balance_p50_minor, delta_balance_minor: 0 })) };
    else if (path === "/assistant/status") body = { enabled: true };
    else if (path.endsWith("/assistant/chat")) body = { text: "Сверка", cards: [{ kind: "table", title: "План и факт",
      data: { as_of: "2026-01-01", items: ids.map(id => ({ event: { id, amount_minor: 12345 }, confirmed_amount_minor: 0 })),
        confirmed_matches: [{ planned_event_id: ids[0], transaction_id: "payment-one", matched_amount_minor: 12345 }],
        proposals: [{ planned_event_id: ids[1], transaction_id: "payment-two", matched_amount_minor: 12345,
          confidence: 0.9, reason: "fixture", auto_confirm: false }] } }] };
    else if (path.endsWith("/planned-events")) body = [];
    else if (path.endsWith("/plan-fact")) body = { proposals: [], items: [], confirmed_matches: [] };
    else {
      // Смежные панели не участвуют в этих проверках и получают явный отказ, а не настоящий API.
      await route.fulfill({ status: 503, json: { error: { code: "fixture_unavailable", message: "Нет тестовых данных панели" } } });
      return;
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Разделы" })).toBeVisible();
});

test("saved 90-day forecast and daily quantiles keep their actual meaning", async ({ page }) => {
  await expect(page.getByText("На конец прогноза", { exact: true })).toBeVisible();
  await expect(page.getByText("за период прогноза · 90 дн.", { exact: true })).toBeVisible();
  await expect(page.getByText("Через 30 дней", { exact: true })).toHaveCount(0);
  await go(page, "Прогноз");
  await expect(page.getByText("На 01.04.2026", { exact: true })).toBeVisible();
  await expect(page.getByTestId("probability-notice")).toBeVisible();
  await page.getByRole("tab", { name: "По дням", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: "Нижняя оценка (p10)", exact: true })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Верхняя оценка (p90)", exact: true })).toBeVisible();
  await expect(page.getByText(/это не гарантированные границы/)).toBeVisible();
  await expect(page.getByTestId("probability-notice")).toBeVisible();
});

test("same-date same-amount scenario targets remain distinct and submit the selected ID", async ({ page }) => {
  await go(page, "Сценарии");
  await page.getByRole("combobox", { name: "Вид сценария", exact: true }).selectOption("delay_event");
  const target = page.getByRole("combobox", { name: "Платёж из базового прогноза", exact: true });
  for (const id of ids) await expect(target.locator(`option[value="${id}"]`)).toContainText(id);
  await target.selectOption({ label: await target.locator(`option[value="${ids[1]}"]`).innerText() });
  const request = page.waitForRequest(r => r.url().endsWith("/scenarios") && r.method() === "POST");
  await page.getByRole("button", { name: "Проверить сценарий", exact: true }).click();
  expect((await request).postDataJSON().changes[0].target_id).toBe(ids[1]);
  await expect(page.getByTestId("scenario-comparison")).toContainText("Разница на 2026-04-01");
});

test("assistant reconciliation identifies both sides of confirmed and proposed matches", async ({ page }) => {
  await goAssistant(page);
  await page.getByLabel("Сообщение ассистенту", { exact: true }).fill("Покажи сверку");
  await page.getByRole("button", { name: "Отправить ассистенту", exact: true }).click();
  const tables = page.locator(".assistant-card table");
  await expect(tables).toHaveCount(3);
  for (const id of ids) await expect(tables.nth(0)).toContainText(id);
  await expect(tables.nth(1)).toContainText(ids[0]);
  await expect(tables.nth(1)).toContainText("payment-one");
  await expect(tables.nth(2)).toContainText(ids[1]);
  await expect(tables.nth(2)).toContainText("payment-two");
});
