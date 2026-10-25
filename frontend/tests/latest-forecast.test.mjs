import assert from "node:assert/strict";
import { test } from "node:test";
import { latestBaseForecast } from "../src/app/latest-forecast.ts";

test("latest base follows history cursors past scenarios and failed jobs without writes", async () => {
  const base = { id: "base", status: "succeeded", base_forecast_id: null };
  const pages = [
    { items: Array.from({ length: 100 }, (_, i) => ({ id: String(i), status: "succeeded", base_forecast_id: "old" })), next_cursor: "cursor+a" },
    { items: [{ id: "failed", status: "failed", base_forecast_id: null }], next_cursor: "cursor+b" },
    { items: [base], next_cursor: "unused" },
  ];
  const requests = [];
  const signal = new globalThis.AbortController().signal;
  const api = { request: async (path, init) => { requests.push(path); assert.equal(init.signal, signal); return pages.shift(); } };
  assert.equal(await latestBaseForecast(api, "company", "account", signal), base);
  assert.equal(requests.length, 3);
  assert.match(requests[1], /cursor=cursor%2Ba/);
  assert.match(requests[2], /cursor=cursor%2Bb/);
});

test("empty history stays empty; unavailable or cyclic history is an error, not no forecast", async () => {
  assert.equal(await latestBaseForecast({ request: async () => ({ items: [], next_cursor: null }) }, "c", "a"), null);
  await assert.rejects(() => latestBaseForecast({ request: async () => { throw new Error("offline"); } }, "c", "a"), /offline/);
  await assert.rejects(() => latestBaseForecast({ request: async () => ({ items: [], next_cursor: "same" }) }, "c", "a"), /курсор/);
});
