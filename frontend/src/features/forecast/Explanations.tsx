import { useQuery } from "@tanstack/react-query";
import { CashCastApi, money } from "../../shared/api";

interface Explanation {
  available: boolean; summary: string;
  items: { kind: string; label: string; amount_minor: number | null; source_ref: string | null }[];
}

// Показываем сохранённые компоненты конкретного расчёта, не выводим причины из графика.
export function Explanations({ api, forecastId }: { api: CashCastApi; forecastId: string }) {
  const query = useQuery({ queryKey: ["explanations", forecastId],
    queryFn: ({ signal }) => api.request<Explanation>(`/forecasts/${forecastId}/explanations`, { signal }) });
  return <section><h3>Причины риска и компоненты</h3>
    {query.isPending && <p role="status">Получаем объяснения…</p>}
    {query.error && <p role="alert">{query.error.message}</p>}
    {query.data && <><p>{query.data.summary}</p>
      {!query.data.available && <p>Подробное объяснение недоступно.</p>}
      <ul>{query.data.items.map((item, index) => <li key={index}>{item.label}
        {item.amount_minor !== null && `: ${money(item.amount_minor)}`}
        {item.source_ref && <small>Источник: {item.source_ref}</small>}</li>)}</ul>
    </>}
  </section>;
}
