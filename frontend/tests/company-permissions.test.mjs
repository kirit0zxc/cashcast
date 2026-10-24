import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createServer } from "vite";

// Проверяем настоящий JSX без DOM, сетевых заглушек и дополнительной test-библиотеки.
let server;
let permissions;
before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
  permissions = await server.ssrLoadModule("/src/shared/company-permissions.tsx");
});
after(async () => { await server?.close(); });

async function render(path, name, props, role) {
  const component = (await server.ssrLoadModule(path))[name];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    return renderToStaticMarkup(createElement(QueryClientProvider, { client },
      createElement(permissions.CompanyPermission, { role }, createElement(component, props))));
  } finally { client.clear(); }
}

const base = { api: {}, companyId: "company", accountId: "account", onChanged() {}, onApplied() {},
  onCommit() {}, revision: 0, initialDate: "2026-10-24", autoRun: false, onDateChange() {} };
const cases = [
  ["imports/StatementImport", "StatementImport", "Проверить файл"],
  ["planning/ObligationImport", "ObligationImport", "Проверить обязательства"],
  ["planning/PlannedEvents", "PlannedEvents", "Добавить платёж"],
  ["planning/PlanFactPanel", "PlanFactPanel", "Применить однозначные совпадения"],
  ["forecast/ForecastPanel", "ForecastPanel", "Рассчитать"],
  ["forecast/ScenarioPanel", "ScenarioPanel", "Проверить сценарий"],
  ["transactions/CategoryEditor", "CategoryEditor", "Сохранить категорию"],
];
for (const [path, name, control] of cases) {
  test(`${name}: owner sees write control; viewer and unknown role do not`, async () => {
    const props = { ...base, transaction: { id: "transaction", category: "sales", category_source: "manual" },
      base: { id: "forecast", points: [{ point_date: "2026-10-25" }] } };
    const modulePath = `/src/features/${path}.tsx`;
    assert.ok((await render(modulePath, name, props, "owner")).includes(control));
    for (const role of ["viewer", "unknown", undefined]) {
      assert.ok(!(await render(modulePath, name, props, role)).includes(control));
    }
  });
}

test("read-only mode keeps category, plans and forecast history readable", async () => {
  const category = await render("/src/features/transactions/CategoryEditor.tsx", "CategoryEditor",
    { ...base, transaction: { category: "sales", category_source: "manual" } }, "viewer");
  assert.ok(category.includes("Выручка") && category.includes("Выбрано вами"));
  assert.ok((await render("/src/features/planning/PlannedEvents.tsx", "PlannedEvents", base, "viewer"))
    .includes("Будущие платежи и обязательства"));
  assert.ok((await render("/src/features/forecast/ForecastPanel.tsx", "ForecastPanel", base, "viewer"))
    .includes("История расчётов"));
});

test("proposal details stay readable during refetch while the payment form is closed", async () => {
  const markup = await render("/src/features/planning/ProposalConfirmation.tsx", "ProposalConfirmation", {
    ...base, event: { id: "plan", due_date: "2026-10-24", direction: "out" },
    proposal: { transaction_id: "transaction", matched_amount_minor: 5876 },
    disabled: true, onConfirm() {}, onEdit() {},
  }, "owner");
  assert.ok(markup.includes('<button type="button">Проверить предложение</button>'));
  assert.ok(!markup.includes("Подтвердить выбранную оплату"));
});
