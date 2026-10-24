import { useQuery } from "@tanstack/react-query";
import { CashCastApi, money, type Explanation } from "../../shared/api";

// Виды компонентов из forecasting/v2: подписи не меняют серверные значения.
const KINDS: Record<string, string> = { planned: "план", recurrence: "регулярное", residual: "остаточный поток",
  risk_minimum: "минимум", scenario: "сценарий" };

// Показываем сохранённые компоненты конкретного расчёта, не выводим причины из графика.
export function Explanations({ api, forecastId }: { api: CashCastApi; forecastId: string }) {
  const query = useQuery({ queryKey: ["explanations", forecastId],
    queryFn: ({ signal }) => api.request<Explanation>(`/forecasts/${forecastId}/explanations`, { signal }) });
  return <section className="panel">
    <span className="label">Из сохранённого расчёта</span>
    <h2>Причины риска и компоненты</h2>
    {query.isPending && <p role="status">Получаем объяснения…</p>}
    {query.error && <p role="alert">{query.error.message}</p>}
    {query.data && <><p>{query.data.summary}</p>
      {!query.data.available && <p className="note">Подробное объяснение недоступно.</p>}
      <ul className="list">{query.data.items.map((item, index) => <li key={index} className="tagged">
        <span className="tag">{KINDS[item.kind] ?? item.kind}</span>
        <span>{item.label}{item.source_ref && <small>Источник: {item.source_ref}</small>}</span>
        <span className="amt">{item.amount_minor !== null ? money(item.amount_minor) : "—"}</span></li>)}</ul>
    </>}
  </section>;
}
