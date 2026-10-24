import { useQuery } from "@tanstack/react-query";
import { useAccount } from "../app/account-context";
import { Link, navigate } from "../app/router";
import { ForecastState } from "../features/forecast/ForecastPanel";
import type { PulseReport, Status } from "../features/pulse/types";
import { money, probability, type Forecast, type PlanFact, type PlannedEvent } from "../shared/api";
import { useCompanyCanWrite } from "../shared/company-permissions";
import { Aura } from "../ui/Aura";
import { Empty } from "../ui/Empty";
import { SpecChart, bandAvailable, compactRub } from "../ui/SpecChart";

const STATUS: Record<Status, string> = { ok: "Спокойно", watch: "Нужно внимание", risk: "Есть риск", unknown: "Недостаточно данных" };
const URGENCY = { now: "сейчас", this_month: "месяц", later: "позже" } as const;
const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const today = () => new Date().toISOString().slice(0, 10);

// Обзор — композиция существующих данных: отдельного dashboard API нет.
// Показываем выбранный сохранённый базовый прогноз; сценарий не подменяет базу.
export function OverviewPage() {
  const { forecast: c } = useAccount();
  const canWrite = useCompanyCanWrite();
  const f = c.forecast.data;
  const ready = f?.status === "succeeded" && !f.base_forecast_id ? f : undefined;
  return <>
    <div className="row" style={{ marginBottom: 18 }}>
      {ready && <span className="chip">срез {ready.as_of}</span>}
      {ready && <span className="chip solid">модель {ready.model_version}</span>}
      {c.working && <span className="chip stale">прогноз обновляется</span>}
      {c.stale && !c.working && <span className="chip stale">прогноз устарел</span>}
      <span style={{ flex: 1 }} />
      {canWrite && <button type="button" className="ghost" onClick={() => navigate("/import")}>Загрузить данные</button>}
      {canWrite && <button type="button" disabled={c.working} onClick={c.run}>Рассчитать</button>}
    </div>
    <ForecastState />
    {!ready && !c.working && !c.forecast.isPending && <Empty title={f?.base_forecast_id ? "Открыт сценарий" : "Нет сохранённого прогноза"}
      text={f?.base_forecast_id ? "Обзор показывает базовый прогноз. Откройте его в разделе «Прогноз»."
        : "Загрузите выписку или нажмите «Рассчитать» — обзор соберётся из результата."} />}
    {ready && <Report forecast={ready} />}
  </>;
}

function Report({ forecast: f }: { forecast: Forecast }) {
  const { api, companyId, accountId } = useAccount();
  const pulse = useQuery({
    queryKey: ["pulse", f.id, null],
    queryFn: ({ signal }) => api.request<PulseReport>(`/forecasts/${f.id}/pulse`, { signal }),
    staleTime: 60_000, retry: false,
  });
  const plans = useQuery({
    queryKey: ["planned-events", companyId, accountId],
    queryFn: ({ signal }) => api.request<PlannedEvent[]>(`/companies/${companyId}/planned-events`, { signal }),
  });
  const date = today();
  const planFact = useQuery({
    queryKey: ["plan-fact", companyId, accountId, date],
    queryFn: ({ signal }) => api.request<PlanFact>(
      `/companies/${companyId}/plan-fact?${new URLSearchParams({ account_id: accountId, as_of: date })}`, { signal }),
  });
  const points = f.points;
  const last = points.at(-1);
  const min = points.reduce<typeof last>((m, p) => !m || p.balance_p50_minor < m.balance_p50_minor ? p : m, undefined);
  const status: Status = pulse.data?.status ?? "unknown";
  const upcoming = (plans.data ?? [])
    .filter(e => e.account_id === accountId && ["planned", "partially_paid"].includes(e.status))
    .sort((a, b) => a.due_date.localeCompare(b.due_date)).slice(0, 5);
  const proposals = planFact.data?.proposals.length ?? 0;

  return <>
    <section className="hero">
      <div>
        <span className="label">Отчёт · счёт {accountId.slice(0, 8).toUpperCase()}</span>
        <h1>Что происходит с&nbsp;деньгами</h1>
        <div className="leader"><span>Факт на</span><i /><span>{day(f.as_of)}</span></div>
        {last && <div className="leader"><span>Прогноз до</span><i /><span>{day(last.point_date)}</span></div>}
        <div className="leader"><span>Режим расчёта</span><i /><span>{f.calculation?.mode === "incremental"
          ? "частичное обновление" : f.calculation ? "полный расчёт" : "нет сведений"}</span></div>
        <div className="leader"><span>Первый минус по медиане</span><i /><span>{f.risk.first_negative_date
          ? day(f.risk.first_negative_date) : f.risk.available ? "не прогнозируется" : "нет оценки"}</span></div>
      </div>
      <div className="statusbox" aria-label="Статус финансового пульса">
        <Aura tone={status} />
        <span className="crop tl" /><span className="crop tr" /><span className="crop bl" /><span className="crop br" />
        <div className="statusword">
          <b>{pulse.isPending ? "Собираем пульс…" : STATUS[status]}</b>
          {pulse.data && <p>{pulse.data.headline}</p>}
          {pulse.error && <p role="alert">Пульс недоступен: {pulse.error.message}</p>}
        </div>
      </div>
    </section>

    <section className="kpis">
      <Kpi label="Начальный остаток прогноза" value={f.opening_balance_minor}
        note={`сохранённый расчёт на ${day(f.as_of)}`} />
      <Kpi label="Минимум в прогнозе" value={min?.balance_p50_minor ?? null}
        note={min ? `${day(min.point_date)} · по медиане` : "нет точек"} />
      <Kpi label="На конец горизонта" value={last?.balance_p50_minor ?? null}
        note={last ? `${day(last.point_date)} · по медиане` : "нет точек"} />
      {f.risk.probability_any_negative === null
        ? <div className="kpi na"><span className="label">Вероятность минуса</span><div className="v">не оценивается</div>
          <div className="s">модель не даёт вероятность — это не 0%</div></div>
        : <div className="kpi"><span className="label">Вероятность минуса</span>
          <div className="v">{probability(f.risk.probability_any_negative)}</div><div className="s">за горизонт прогноза</div></div>}
    </section>

    <section className="grid2">
      <div>
        <div className="panel">
          <span className="dots" aria-hidden="true">● ● ●</span>
          <span className="label">Прогноз остатка · {points.length} дн.</span>
          <h2>Хватит ли денег на ближайший месяц</h2>
          <SpecChart points={points} label="Обзор: медиана остатка и диапазон p10–p90" />
          <div className="legend">
            <span><i style={{ background: "var(--ink)" }} />медиана</span>
            <span>{bandAvailable(points)
              ? <><i style={{ background: "radial-gradient(var(--ink) 30%, transparent 35%) 0 0/4px 4px" }} />диапазон p10–p90</>
              : "диапазон недоступен — данных мало"}</span>
            <Link to="/forecast">таблица по дням →</Link>
          </div>
        </div>
        {(f.risk.first_negative_date || status === "risk") && <div className="warn" role="status">
          <div className="sign"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M12 3 2 21h20L12 3z" /><path d="M12 10v5M12 18h.01" /></svg>WARNING</div>
          <div className="body">
            <b>{f.risk.first_negative_date ? `Возможный минус с ${day(f.risk.first_negative_date)}` : STATUS.risk}</b>
            <p>{pulse.data?.cash.message ?? `Максимальный дефицит по прогнозу: ${money(f.risk.max_deficit_minor)}.`}</p>
            <button type="button" onClick={() => navigate("/pulse")}>Открыть пульс</button>
          </div>
        </div>}
      </div>
      <div className="stack">
        <div className="panel dash"><span className="label">Ближайшие платежи</span>
          {plans.error && <p role="alert">{plans.error.message}</p>}
          {plans.data && !upcoming.length && <p>Плановых платежей нет.</p>}
          <ul className="list">{upcoming.map(e => <li key={e.id}>
            <span className="d">{e.due_date.slice(8)}<small>{MONTHS[Number(e.due_date.slice(5, 7)) - 1]}</small></span>
            <span>{e.counterparty_name ?? e.counterparty_ref ?? "Плановый платёж"}
              {e.remaining_amount_minor !== e.amount_minor && <small>остаток из {money(e.amount_minor)}</small>}</span>
            <span className="amt">{e.direction === "out" ? "−" : "+"}{money(e.remaining_amount_minor)}</span>
          </li>)}</ul>
          <Link to="/payments">все платежи →</Link>
        </div>
        <div className="panel"><span className="label">Что рекомендует пульс</span>
          {pulse.data && !pulse.data.actions.length && <p>Срочных действий нет.</p>}
          <ul className="list">{pulse.data?.actions.slice(0, 4).map((a, i) => <li key={i} className="tagged">
            <span className={`tag${a.urgency === "now" ? " now" : ""}`}>{URGENCY[a.urgency]}</span>
            <span>{a.title}</span>
            <span className="amt">{a.amount_minor ? `${compactRub(a.amount_minor)} ₽` : ""}</span>
          </li>)}</ul>
        </div>
        {proposals > 0 && <div className="panel dash"><span className="label">Сверка оплат</span>
          <p>Есть предложения сопоставить оплаты с планами: {proposals}. Это ещё не оплата.</p>
          <Link to="/reconciliation">проверить →</Link></div>}
      </div>
    </section>
  </>;
}

function Kpi({ label, value, note }: { label: string; value: number | null; note: string }) {
  if (value === null) return <div className="kpi na"><span className="label">{label}</span>
    <div className="v">недоступно</div><div className="s">{note}</div></div>;
  return <div className="kpi"><span className="label">{label}</span>
    <div className={`v${value < 0 ? " neg" : ""}`}>{money(value)}</div><div className="s">{note}</div></div>;
}
