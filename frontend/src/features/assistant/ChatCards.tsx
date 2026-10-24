import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CashCastApi, money, type Forecast, type Job } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { ForecastView } from "../forecast/ForecastPanel";
import { PulseView } from "../pulse/PulsePanel";
import type { PulseReport } from "../pulse/types";
import type { ChatCard, ChatReply } from "./types";
import { SpecLines } from "../../ui/SpecChart";

const labels: Record<string, string> = {
  amount_minor: "Сумма", remaining_amount_minor: "Осталось оплатить", direction: "Направление",
  due_date: "Дата платежа", booked_on: "Дата операции", point_date: "Дата", category: "Категория",
  counterparty_name: "Контрагент", status: "Статус", source: "Источник", count: "Количество",
  id: "ID", account_id: "Счёт", forecast_id: "Прогноз", event_id: "Плановый платёж",
  transaction_id: "Операция", planned_event_id: "Обязательство", matched_amount_minor: "Подтверждаемая оплата",
  as_of: "Дата среза", horizon_days: "Горизонт, дней", kind: "Вид", shift_days: "Перенос, дней",
  factor: "Множитель", on_date: "Дата", description: "Описание", currency: "Валюта",
  body: "Параметры", changes: "Изменения", import_id: "Импорт", import_kind: "Тип файла",
  total_rows: "Строк", error_count: "Ошибок", inserted: "Добавлено", skipped_existing: "Уже существовали",
  period_start: "Начало периода", period_end: "Конец периода", valid_count: "Корректных строк",
  balance_p50_minor: "Остаток", base_balance_p50_minor: "База", scenario_balance_p50_minor: "Сценарий",
  delta_balance_minor: "Изменение", confirmed_amount_minor: "Оплачено", label: "Причина",
};
const values: Record<string, string> = { in: "Приход", out: "Расход", pending: "Ожидает подтверждения",
  confirmed: "Выполнено", cancelled: "Отменено", planned: "Запланировано", paid: "Оплачено",
  partially_paid: "Частично оплачено", statement: "Выписка", obligations: "Обязательства" };

const KINDS: Record<string, string> = { table: "таблица", forecast: "прогноз", comparison: "сценарий", pulse: "пульс",
  action: "предложение действия", job: "расчёт", import: "импорт" };

function cell(key: string, value: unknown): string {
  if (value == null) return "—";
  if (key.endsWith("_minor") && typeof value === "number") return money(value);
  if (typeof value === "object") return JSON.stringify(value);
  return values[String(value)] ?? String(value);
}

// Таблицы используют только серверные строки; значения выводятся текстом с экранированием React.
export function DataTable({ data }: { data: Record<string, unknown> }) {
  if (Array.isArray(data.confirmed_matches) && Array.isArray(data.proposals)) {
    const items = (data.items as { event: Record<string, unknown>; confirmed_amount_minor: number }[])
      .map(item => ({ ...item.event, confirmed_amount_minor: item.confirmed_amount_minor }));
    return <><p>Срез: {String(data.as_of)}</p><h5>Обязательства</h5><DataTable data={{ items }} />
      <h5>Подтверждённые оплаты</h5><DataTable data={{ items: data.confirmed_matches }} />
      <h5>Предложения сверки — ещё не применены</h5><DataTable data={{ items: data.proposals }} /></>;
  }
  const rows = (Array.isArray(data.items) ? data.items : Array.isArray(data.points) ? data.points : [data])
    .filter((v): v is Record<string, unknown> => !!v && typeof v === "object");
  const keys = [...new Set(rows.flatMap(r => Object.keys(r)))].filter(k =>
    !["account_id", "company_id", "input_snapshot", "_incremental_state"].includes(k));
  return <>
    {rows.length ? <div className="scroll"><table className="ops"><thead><tr>
      {keys.map(k => <th key={k}>{labels[k] ?? k}</th>)}</tr></thead><tbody>
      {rows.map((row, i) => <tr key={i}>{keys.map(k => <td key={k}>{cell(k, row[k])}</td>)}</tr>)}
    </tbody></table></div> : <p>Нет данных за выбранный период.</p>}
    {!!data.next_cursor && <p>Показана страница. Для продолжения попросите следующую страницу.</p>}
    {!!data.truncated && <p>Показана только часть списка.</p>}
  </>;
}

function ArgumentsView({ data }: { data: Record<string, unknown> }) {
  return <dl>{Object.entries(data).map(([key, value]) => <div key={key}>
    <dt>{labels[key] ?? key}</dt><dd>{value && typeof value === "object"
      ? Array.isArray(value) ? value.map((v, i) => <ArgumentsView key={i} data={v} />)
        : <ArgumentsView data={value as Record<string, unknown>} /> : cell(key, value)}</dd>
  </div>)}</dl>;
}

function ActionCard({ card, api, companyId, accountId, onReply }: CardProps) {
  const canWrite = useCompanyCanWrite();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Статус берём из истории чата: её обновляет ответ сервера на confirm/cancel.
  const state = String(card.data.status);
  const expired = Date.parse(String(card.data.expires_at)) <= Date.now();
  async function decide(decision: "confirm" | "cancel") {
    setBusy(true); setError("");
    try {
      const result = await api.post<ChatReply>(`/companies/${companyId}/accounts/${accountId}/assistant/actions/${card.data.action_id}`,
        { decision });
      const action = result.cards.find(c => c.kind === "action") ?? null;
      const actual = action?.data.status;
      onReply(result, actual === "confirmed" ? action : null);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось подтвердить"); }
    finally { setBusy(false); }
  }
  return <div className="assistant-action" data-testid="assistant-action">
    <p><strong>{values[state] ?? state}</strong>. Счёт: {String(card.data.account_id)}.</p>
    <ArgumentsView data={card.data.arguments as Record<string, unknown>} />
    <p>Подтверждение действительно до {new Date(String(card.data.expires_at)).toLocaleTimeString("ru-RU")}.
      Если данные счёта изменились, потребуется новое предложение.</p>
    {state === "pending" && canWrite && <div className="row">
      <button type="button" disabled={busy || expired} onClick={() => void decide("confirm")}>Подтвердить действие</button>
      <button type="button" disabled={busy} onClick={() => void decide("cancel")}>Отменить предложение</button>
    </div>}
    {expired && state === "pending" && <p>Срок предложения истёк. Попросите ассистента подготовить новое.</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

function JobCard({ api, card }: CardProps) {
  const job = useQuery({ queryKey: ["assistant-job", card.data.job_id], retry: false,
    queryFn: () => api.request<Job>(`/jobs/${card.data.job_id}`),
    refetchInterval: q => q.state.error || ["succeeded", "failed"].includes(q.state.data?.status ?? "") ? false : 1500 });
  const forecast = useQuery({ queryKey: ["forecast", card.data.forecast_run_id], retry: false,
    queryFn: () => api.request<Forecast>(`/forecasts/${card.data.forecast_run_id}`),
    enabled: job.data?.status === "succeeded" });
  return <><p>Расчёт: {job.data?.status ?? "ожидаем"}. ID: {String(card.data.forecast_run_id)}</p>
    {job.data?.status === "failed" && <p role="alert">Ошибка расчёта: {job.data.error_code}</p>}
    {[job.error, forecast.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
    {forecast.data?.status === "succeeded" && <ForecastView forecast={forecast.data} />}</>;
}

interface CardProps { card: ChatCard; api: CashCastApi; companyId: string; accountId: string;
  /** confirmed — карточка действия, если сервер подтвердил запись; иначе null. */
  onReply: (reply: ChatReply, confirmed: ChatCard | null) => void }

export function ChatCardView(props: CardProps) {
  const { card } = props;
  return <section className={`assistant-card kind-${card.kind}`}><span className="label">{KINDS[card.kind] ?? card.kind}</span><h3>{card.title}</h3>
    {card.kind === "action" ? <ActionCard {...props} />
      : card.kind === "forecast" ? card.data.status === "succeeded"
        ? <ForecastView forecast={card.data as unknown as Forecast} /> : <DataTable data={card.data} />
      : card.kind === "pulse" ? <PulseView data={card.data as unknown as PulseReport} />
      : card.kind === "job" ? <JobCard {...props} />
      : card.kind === "comparison" ? <>
        <SpecLines label="Сравнение базы и сценария в чате" markMin={false}
          dates={(card.data.points as { point_date: string }[]).map(p => p.point_date)} series={[
            { name: "сценарий", style: "ink", values: (card.data.points as { scenario_balance_p50_minor: number }[]).map(p => p.scenario_balance_p50_minor) },
            { name: "база", style: "dash", values: (card.data.points as { base_balance_p50_minor: number }[]).map(p => p.base_balance_p50_minor) },
          ]} />
        <details><summary>Таблица по дням</summary><DataTable data={card.data} /></details>
      </> : <DataTable data={card.data} />}
  </section>;
}
