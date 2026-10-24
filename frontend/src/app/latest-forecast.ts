import type { CashCastApi, ForecastHistoryEntry, Page } from "../shared/api";

// Общая история содержит и сценарии, и неуспешные задания. Ищем первую успешную
// базу во всех страницах, не подменяя отсутствие на первой странице отсутствием вообще.
export async function latestBaseForecast(api: CashCastApi, companyId: string, accountId: string,
  signal?: AbortSignal): Promise<ForecastHistoryEntry | null> {
  let cursor: string | null = null;
  const seen = new Set<string>();
  do {
    const params = new URLSearchParams({ account_id: accountId, limit: "100" });
    if (cursor) params.set("cursor", cursor);
    const page = await api.request<Page<ForecastHistoryEntry>>(`/companies/${companyId}/forecasts?${params}`, { signal });
    const base = page.items.find(item => item.status === "succeeded" && !item.base_forecast_id);
    if (base) return base;
    cursor = page.next_cursor;
    if (cursor && seen.has(cursor)) throw new Error("Не удалось прочитать историю: повтор курсора");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return null;
}
