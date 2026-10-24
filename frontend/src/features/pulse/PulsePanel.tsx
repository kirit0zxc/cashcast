import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CashCastApi, money, rublesToMinor } from "../../shared/api";
import { Aura } from "../../ui/Aura";
import { Leaders, Tabs, dayMonth } from "../../ui/Blank";
import { SpecLines } from "../../ui/SpecChart";
import type { PulseReport, Status } from "./types";

const labels: Record<Status, string> = { ok: "Спокойно", watch: "Нужно внимание", risk: "Есть риск", unknown: "Недостаточно данных" };
const URGENCY = { now: "сейчас", this_month: "месяц", later: "позже" } as const;
type Tab = "cash" | "money" | "clients" | "actions";

// Разделы одного серверного отчёта: касса, расходы, клиенты и шаги. Все числа — из API,
// оценки разных направлений не суммируются; evidence и ограничения остаются видимыми.
export function PulsePanel({ api, forecastId }: { api: CashCastApi; forecastId: string }) {
  const [input, setInput] = useState("");
  const [buffer, setBuffer] = useState<number | null>(null);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["pulse", forecastId, buffer],
    queryFn: ({ signal }) => api.request<PulseReport>(`/forecasts/${forecastId}/pulse${buffer === null ? "" : `?buffer_minor=${buffer}`}`, { signal }),
    staleTime: 60_000, retry: false,
  });
  function apply(event: FormEvent) {
    event.preventDefault();
    try {
      const text = input.trim();
      const value = !text ? null : /^0+(?:[.,]0{1,2})?$/.test(text) ? 0 : rublesToMinor(text);
      if (value !== null && value < 0) throw new Error("Подушка не может быть отрицательной");
      setBuffer(value); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Проверьте сумму"); }
  }
  const status = query.data?.status ?? "unknown";
  return <section aria-label="Финансовый пульс" data-testid="pulse-panel">
    <div className="hero top0">
      <div className="statusbox" aria-label="Статус финансового пульса">
        <Aura tone={status} />
        <span className="crop tl" /><span className="crop tr" /><span className="crop bl" /><span className="crop br" />
        <div className="statusword">
          <b>{query.isPending ? "Собираем пульс…" : labels[status]}</b>
          {query.data && <p>{query.data.headline}</p>}
        </div>
      </div>
      <div className="cushion">
        <span className="label">Подушка безопасности</span>
        {query.data ? <>
          <div className="cushion-sum">{money(query.data.cash.buffer_minor)}</div>
          <p className="cushion-src">{query.data.cash.buffer_source === "user" ? "задана вами"
            : "рассчитали по вашим расходам — столько стоит держать на счёте"}</p>
          {(() => {
            const c = query.data.cash;
            if (c.status === "unknown") return <p className="cushion-verdict tone-unknown">Хватит ли запаса — оценка недоступна: мало данных.</p>;
            if (c.first_gap_date) return <p className="cushion-verdict tone-risk">Запаса не хватит с {dayMonth(c.first_gap_date)}.</p>;
            return <p className="cushion-verdict tone-ok">Запаса хватает на весь период прогноза.</p>;
          })()}
        </> : query.isPending ? <p role="status">Считаем…</p> : null}
        <form className="cushion-form" onSubmit={apply}>
          <label>Свой запас, ₽
            <input value={input} inputMode="decimal" placeholder="например, 300 000"
              aria-label="Подушка, ₽ (пусто — оценить автоматически)" onChange={e => setInput(e.target.value)} /></label>
          <button disabled={query.isFetching}>Проверить подушку</button>
        </form>
        <small>Оставьте поле пустым — посчитаем сами.</small>
      </div>
    </div>
    {error && <p role="alert">{error}</p>}
    {query.error && <p role="alert">{query.error.message}</p>}
    {query.data && <PulseView data={query.data} />}
  </section>;
}

export function PulseView({ data: p }: { data: PulseReport }) {
  const [tab, setTab] = useState<Tab>("cash");
  return <>
    <Tabs label="Разделы пульса" value={tab} onChange={setTab} items={[
      ["cash", `Касса и подушка · ${labels[p.cash.status]}`],
      ["money", `Расходы · ${labels[p.money.status]}`],
      ["clients", p.clients.applicable ? `Клиенты · ${labels[p.clients.status]}` : "Клиенты"],
      ["actions", `Шаги · ${p.actions.length}`],
    ]} />
    {tab === "cash" && <CashTab p={p} />}
    {tab === "money" && <MoneyTab p={p} />}
    {tab === "clients" && <ClientsTab p={p} />}
    {tab === "actions" && <ActionsTab p={p} />}
    <details><summary>Источники и ограничения пульса</summary>
      <p className="note">Прогноз {p.forecast_id}; модель {p.model_version}; вход {p.data_version}; метод {p.method_version}.</p>
      <ul className="plain">{[...new Set([...p.warnings, ...p.cash.assumptions, ...p.money.assumptions])].map((w, i) => <li key={i}>{w}</li>)}</ul>
    </details>
  </>;
}

function CashTab({ p }: { p: PulseReport }) {
  const cash = p.cash;
  const days = cash.chart.days;
  return <div className="grid2 top0">
    <section className="panel">
      <span className="label">Касса · {days.length} дн.</span>
      <h2>Нехватка денег и возможные действия</h2>
      <p>{cash.message}</p>
      {cash.structural_shortfall && <p className="errors">Расходы устойчиво превышают поступления. Перенос платежей или заём могут лишь отложить проблему.</p>}
      <SpecLines label="Пульс: сохранённая база и гипотетический план" dates={days} series={[
        { name: "остаток", values: cash.chart.base_minor, style: "ink" },
        ...(cash.chart.after_plan_minor ? [{ name: "после плана", values: cash.chart.after_plan_minor, style: "dash" as const }] : []),
        ...(cash.chart.if_owner_withdraws_minor ? [{ name: "если выводить", values: cash.chart.if_owner_withdraws_minor, style: "thin" as const }] : []),
        { name: "подушка", values: days.map(() => cash.chart.buffer_minor), style: "coral" },
      ]} />
      <div className="legend">
        <span><i style={{ background: "var(--ink)" }} />ожидаемый остаток</span>
        {cash.chart.after_plan_minor && <span><i style={{ background: "repeating-linear-gradient(90deg, var(--ink) 0 5px, transparent 5px 8px)" }} />гипотетический план</span>}
        {cash.chart.if_owner_withdraws_minor && <span><i style={{ background: "var(--ink-2)", height: 2 }} />если выводить как обычно</span>}
        <span><i style={{ background: "var(--coral)", height: 2 }} />подушка</span>
      </div>
    </section>
    <section className="stack">
      {cash.plan ? <div className="panel dash">
        <span className="label">{cash.plan.resolved ? "План закрывает нехватку" : "План не закрывает всю нехватку"}</span>
        <h3>{cash.plan.title}</h3>
        <ol className="steps">{cash.plan.steps.map((step, i) => <li key={i}><b>{step.title}</b>
          {step.amount_minor > 0 && <span className="amt"> · {money(step.amount_minor)}</span>}
          {step.details.map((d, j) => <small key={j}>{d}</small>)}</li>)}</ol>
        <Leaders rows={[
          ["Финансирование", money(cash.plan.credit_minor)],
          ["Проценты в расчёте", money(cash.plan.credit_cost_minor)],
          ["Поступления −20%", cash.plan.holds_if_inflows_drop_20pct ? "остаток не уходит в минус" : "возможен минус"],
        ]} />
      </div> : cash.status === "unknown"
        ? <div className="empty"><b>План недоступен</b>Недостаточно данных, чтобы подтвердить сохранность подушки.</div>
        : <div className="empty"><b>План не сформирован</b>Проверьте состояние кассы и ограничения расчёта.</div>}
      {cash.suggestions.map((s, i) => <div key={i} className="panel"><b>{s.title}</b>
        {s.details.map((d, j) => <small key={j}>{d}</small>)}</div>)}
    </section>
  </div>;
}

function MoneyTab({ p }: { p: PulseReport }) {
  const m = p.money;
  return <>
    <section className="kpis">
      <div className="kpi"><span className="label">Потери в год</span><div className="v">{money(m.loss_per_year_minor)}</div><div className="s">по фактам выписки</div></div>
      <div className="kpi"><span className="label">Возможности в год</span><div className="v">{money(m.opportunity_per_year_minor)}</div><div className="s">оценка</div></div>
      <div className="kpi"><span className="label">Разовые потери</span><div className="v">{money(m.one_off_loss_minor)}</div><div className="s">за последний год</div></div>
      <div className="kpi"><span className="label">Застряло</span><div className="v">{money(m.frozen_minor)}</div><div className="s">ошибки в реквизитах</div></div>
    </section>
    <p className="note">Это оценки отдельных направлений: они могут пересекаться и не складываются в общий эффект. Условия каждого варианта — в подробностях.</p>
    {!m.findings.length && <div className="empty"><b>Находок нет</b>По имеющимся данным. Это не гарантия отсутствия лишних расходов.</div>}
    <div className="proposals">{m.findings.map((finding, i) => <article key={i} className="panel dash proposal">
      <div className="row between">
        <span className={`tag${finding.certainty === "fact" ? " now" : ""}`}>{finding.certainty === "fact" ? "факт выписки" : "оценка"}</span>
        <span className="label">{finding.period === "year" ? "в год" : "за последний год"}</span>
      </div>
      <h3>{finding.title} — {money(finding.amount_minor)}</h3>
      <p>{finding.action}</p>
      {finding.blocked_by_cash_gap && <p className="note">Совет отложен: впереди возможная нехватка денег.</p>}
      <details><summary>Доказательства · {finding.evidence.length}</summary>
        <ul className="plain">{finding.evidence.map((e, j) => <li key={j}>{e}</li>)}</ul></details>
    </article>)}</div>
  </>;
}

function ClientsTab({ p }: { p: PulseReport }) {
  const c = p.clients;
  if (!c.applicable) return <div className="empty"><b>Блок не применим</b>{c.message}</div>;
  return <div className="grid2 top0">
    <section className="panel">
      <span className="label">Зависимость от клиентов</span>
      <h2>{c.message}</h2>
      {c.top_client && <Leaders rows={[["Крупнейший клиент", `${c.top_client.name} · ${Math.round(c.top_client.share * 100)}%`],
        ["Оценка", c.top_client.grade_label]]} />}
      {c.at_risk.length > 0 && <span className="label">Доля выручки клиентов в зоне внимания</span>}
      <div className="bars">{c.at_risk.map((r, i) => <div key={i} className="bar">
        <div className="row between"><span>{r.name ?? "Клиент"} · {r.grade_label}</span><span className="mono">{Math.round(r.share * 100)}%</span></div>
        <div className="code" style={{ width: `${Math.max(4, r.share * 100)}%` }} />
        {r.reasons.map((reason, j) => <small key={j}>{reason}</small>)}
      </div>)}</div>
    </section>
    <section className="stack">{c.stress.map((s, i) => <details key={i} className="panel dash" open={i === 0}>
      <summary>{s.title}</summary><p>{s.text}</p>
      <Leaders rows={[["Первая нехватка", s.first_gap_date ? dayMonth(s.first_gap_date) : "не возникает"],
        ["Худший день", money(s.worst_day_shortfall_minor)]]} />
      <small>Основание сценария: {s.basis}</small></details>)}
      {!c.stress.length && <div className="empty"><b>Стресс-сценариев нет</b>Недостаточно данных о клиентах.</div>}
    </section>
  </div>;
}

function ActionsTab({ p }: { p: PulseReport }) {
  if (!p.actions.length) return <div className="empty"><b>Нет обоснованных действий</b>По текущим данным.</div>;
  return <section className="panel"><span className="label">Следующие шаги · сначала срочные</span>
    <ul className="list">{p.actions.map((a, i) => <li key={i} className="tagged">
      <span className={`tag${a.urgency === "now" ? " now" : ""}`}>{URGENCY[a.urgency]}</span>
      <span><b>{a.title}</b><small>{a.why}</small></span>
      <span className="amt">{a.amount_minor ? money(a.amount_minor) : ""}</span>
    </li>)}</ul>
  </section>;
}
