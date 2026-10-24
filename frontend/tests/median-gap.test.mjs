import assert from "node:assert/strict";
import { test } from "node:test";
import { medianGap } from "../src/features/forecast/median-gap.ts";

const forecast = (balances, opening = 26040000) => ({
  as_of: "2026-08-01", opening_balance_minor: opening,
  points: balances.map((balance, i) => ({ point_date: `2026-08-0${i + 2}`, balance_p50_minor: balance })),
  risk: { available: false, first_negative_date: null, max_deficit_minor: null, probability_any_negative: null },
});

test("positive screenshot curve has no median deficit even without probability", () => {
  assert.deepEqual(medianGap(forecast([26000000, 24790000, 28950000])), {
    firstNegativeDate: null, hasForecast: true, maxDeficitMinor: 0,
  });
});

test("negative curve remains visible without a probability estimate", () => {
  assert.deepEqual(medianGap(forecast([10, -500, -100, 0])), {
    firstNegativeDate: "2026-08-03", hasForecast: true, maxDeficitMinor: 500,
  });
});

test("existing opening deficit is visible even if the next day recovers", () => {
  assert.deepEqual(medianGap(forecast([0, 100], -700)), {
    firstNegativeDate: "2026-08-01", hasForecast: true, maxDeficitMinor: 700,
  });
});

test("missing forecast is not a no-gap forecast; zero is not a deficit", () => {
  assert.deepEqual(medianGap(forecast([], null)), {
    firstNegativeDate: null, hasForecast: false, maxDeficitMinor: null,
  });
  assert.equal(medianGap(forecast([0], 0)).firstNegativeDate, null);
});
