import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CashCastApi, type ForecastHistoryEntry, type Page } from "../../shared/api";

const statuses: Record<string, string> = {
  pending: "В очереди", running: "Выполняется", succeeded: "Готов", failed: "Ошибка",
};

export function ForecastHistory({ api, companyId, accountId, disabled, onOpen }: {
  api: CashCastApi; companyId: string; accountId: string; disabled: boolean;
  onOpen: (entry: ForecastHistoryEntry) => void;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["forecast-history", companyId, accountId, cursor],
    queryFn: ({ signal }) => api.request<Page<ForecastHistoryEntry>>(
      `/companies/${companyId}/forecasts?account_id=${accountId}&limit=10`
      + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""), { signal }),
    enabled: !!accountId,
    // Старый расчёт без job не запускаем заново и не опрашиваем бесконечно.
    refetchInterval: query => query.state.data?.items.some(item => item.job_id
      && ["pending", "running"].includes(item.status)) ? 3000 : false,
  });
  return <details><summary>История расчётов</summary>
    <p>Открытие сохранённого результата не запускает новый расчёт. Сначала новые записи.</p>
    {history.isPending && <p role="status">Загружаем историю…</p>}
    {history.error && <p role="alert">{history.error.message}</p>}
    {history.data && <>
      {!history.data.items.length && <p>Сохранённых расчётов пока нет.</p>}
      <div className="scroll"><table aria-label="История расчётов"><thead><tr>
        <th>Создан</th><th>Дата среза</th><th>Вид</th><th>Модель</th><th>Состояние</th><th>Действие</th>
      </tr></thead><tbody>{history.data.items.map(item => <tr key={item.id} data-testid={`history-row-${item.id}`}>
        <td>{new Date(item.created_at).toLocaleString("ru-RU")}</td><td>{item.as_of}</td>
        <td>{item.base_forecast_id ? "Сценарий" : "Прогноз"}</td><td>{item.model_version}</td>
        <td>{statuses[item.status] ?? item.status}{item.error_code && `: ${item.error_code}`}</td>
        <td><button type="button" disabled={disabled} onClick={() => onOpen(item)}>Открыть</button></td>
      </tr>)}</tbody></table></div>
      <div className="row">
        <button type="button" disabled={!cursor || history.isFetching} onClick={() => setCursor(null)}>В начало истории</button>
        <button type="button" disabled={!history.data.next_cursor || history.isFetching}
          onClick={() => setCursor(history.data!.next_cursor)}>Следующие 10 расчётов</button>
      </div>
    </>}
  </details>;
}
