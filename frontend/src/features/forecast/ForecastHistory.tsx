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
  return <section className="panel flat">
    <div className="panel-head"><div><h2>Сохранённые расчёты</h2>
      <span className="label">Открытие не запускает новый расчёт · сначала новые</span></div></div>
    {history.isPending && <p role="status">Загружаем историю…</p>}
    {history.error && <p role="alert">{history.error.message}</p>}
    {history.data && <>
      {!history.data.items.length && <div className="empty"><b>Сохранённых расчётов пока нет</b>Рассчитайте прогноз — он появится здесь.</div>}
      {history.data.items.length > 0 && <div className="scroll"><table className="ops" aria-label="История расчётов"><thead><tr>
        <th>Создан</th><th>Дата среза</th><th>Вид</th><th>Модель</th><th>Состояние</th><th>Действие</th>
      </tr></thead><tbody>{history.data.items.map(item => <tr key={item.id} data-testid={`history-row-${item.id}`}>
        <td className="mono nowrap">{new Date(item.created_at).toLocaleString("ru-RU")}</td>
        <td className="mono">{item.as_of}</td>
        <td>{item.base_forecast_id ? <span className="tag">Сценарий</span> : "Прогноз"}</td>
        <td className="mono">{item.model_version}</td>
        <td><span className={`tag${item.status === "succeeded" ? "" : item.status === "failed" ? " status-failed" : " status-partially_paid"}`}>
          {statuses[item.status] ?? item.status}</span>{item.error_code && <small>{item.error_code}</small>}</td>
        <td><button type="button" className="ghost" disabled={disabled} onClick={() => onOpen(item)}>Открыть</button></td>
      </tr>)}</tbody></table></div>}
      <div className="pager"><small>По 10 расчётов на странице.</small>
        <button type="button" className="ghost" disabled={!cursor || history.isFetching} onClick={() => setCursor(null)}>В начало истории</button>
        <button type="button" disabled={!history.data.next_cursor || history.isFetching}
          onClick={() => setCursor(history.data!.next_cursor)}>Следующие 10 расчётов</button>
      </div>
    </>}
  </section>;
}
