import type { Forecast } from "../../shared/api";

// Минус на сохранённой кривой не зависит от доступности вероятностной оценки.
// Учитываем и начальный остаток: уже существующий дефицит нельзя скрывать.
export function medianGap(forecast: Pick<Forecast, "as_of" | "opening_balance_minor" | "points">) {
  const values = [
    ...(forecast.opening_balance_minor === null ? []
      : [{ date: forecast.as_of, balance: forecast.opening_balance_minor }]),
    ...forecast.points.map(p => ({ date: p.point_date, balance: p.balance_p50_minor })),
  ];
  const first = values.find(p => p.balance < 0);
  return {
    firstNegativeDate: first?.date ?? null,
    hasForecast: forecast.points.length > 0,
    maxDeficitMinor: values.length ? Math.max(0, ...values.map(p => -p.balance)) : null,
  };
}
