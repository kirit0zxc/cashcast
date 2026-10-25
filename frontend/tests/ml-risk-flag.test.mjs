import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

let server, MLRiskFlag;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom",
    optimizeDeps: { noDiscovery: true, entries: [] } });
  ({ MLRiskFlag } = await server.ssrLoadModule("/src/features/forecast/MLRiskFlag.tsx"));
});
after(async () => { await server?.close(); });
const render = assessment => renderToStaticMarkup(createElement(MLRiskFlag,
  { forecast: { risk: { probability_any_negative: 0.42, ml_flag: assessment } } }));

// Недоступность модели не должна выглядеть как отсутствие риска.
test("ML: yes/no remain separate from probability, unavailable never becomes no", () => {
  assert.match(render({ available: true, flag: true }), /риск разрыва — да/);
  assert.match(render({ available: true, flag: false }), /риск разрыва — нет/);
  const unavailable = render({ available: false, flag: false, reason: "model_unavailable" });
  assert.match(unavailable, /не оценено/);
  assert.doesNotMatch(unavailable, /разрыва — нет|42%/);
  assert.equal(render(null), "");
});

test("ML history-only scope is visible and scenarios are explicitly unsupported", () => {
  assert.match(render({ available: true, flag: false }), /Планы и сценарии не учитываются/);
  assert.match(render({ available: false, flag: null, reason: "scenario_not_supported" }),
    /Изменения сценария этим детектором не оцениваются/);
});
