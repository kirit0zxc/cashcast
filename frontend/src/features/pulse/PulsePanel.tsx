import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CashCastApi, money, rublesToMinor } from "../../shared/api";
import type { PulseReport, Status } from "./types";

const labels: Record<Status, string> = { ok: "Спокойно", watch: "Нужно внимание", risk: "Есть риск", unknown: "Недостаточно данных" };
// Короткая ось не обрезает миллионы на узком экране; подсказка хранит точные копейки.
const axisRubles = new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 });

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
  return <section aria-label="Финансовый пульс" data-testid="pulse-panel">
    <h3>Финансовый пульс</h3>
    <p>Что может случиться и что можно сделать. Данные того же сохранённого прогноза; просмотр не меняет платежи.</p>
    <form className="row" onSubmit={apply}>
      <label>Подушка, ₽ (пусто — оценить автоматически)<input value={input} inputMode="decimal" onChange={e => setInput(e.target.value)} /></label>
      <button disabled={query.isFetching}>Проверить подушку</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {query.isPending && <p role="status">Собираем финансовый пульс…</p>}
    {query.error && <p role="alert">{query.error.message}</p>}
    {query.data && <PulseView data={query.data} />}
  </section>;
}

export function PulseView({ data: p }: { data: PulseReport }) {
  const cash = p.cash;
  const chart = cash.chart.days.map((day, i) => ({ day, base: cash.chart.base_minor[i],
    after: cash.chart.after_plan_minor?.[i], buffer: cash.buffer_minor }));
  return <>
    <p><strong>{labels[p.status]}</strong> · срез {p.as_of}</p>
    <p>{p.headline}</p>
    <h4>Нехватка денег и возможные действия</h4>
    <p>{cash.message} Подушка: {money(cash.buffer_minor)} ({cash.buffer_source === "user" ? "задана вами" : "модельная оценка"}).</p>
    {cash.structural_shortfall && <p>Расходы устойчиво превышают поступления. Перенос платежей или заём могут лишь отложить проблему.</p>}
    <div className="chart" role="img" aria-label="Пульс: сохранённая база и гипотетический план">
      <ResponsiveContainer width="100%" height={250}><LineChart data={chart}>
        <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" /><YAxis width={100} tickFormatter={v => `${axisRubles.format(Number(v) / 100)} ₽`} />
        <Tooltip formatter={v => money(Number(v))} />
        <Line dataKey="base" name="Сохранённая медиана" stroke="#315d9d" dot={false} />
        <Line dataKey="after" name="Гипотетический план" stroke="#17805c" dot={false} />
        <Line dataKey="buffer" name="Подушка" stroke="#b97928" dot={false} strokeDasharray="4 4" />
      </LineChart></ResponsiveContainer>
    </div>
    {cash.plan && <>
      <p><strong>{cash.plan.title}</strong>. {cash.plan.resolved ? "В пределах горизонта подушка сохраняется." : "Этот вариант не устраняет всю нехватку."}</p>
      <p>Финансирование: {money(cash.plan.credit_minor)}. Проценты в расчёте: {money(cash.plan.credit_cost_minor)}.</p>
      <ul>{cash.plan.steps.map((step, i) => <li key={i}>{step.title}<ul>{step.details.map((d, j) => <li key={j}>{d}</li>)}</ul></li>)}</ul>
      <p>Стресс со снижением оценочных поступлений на 20%: {cash.plan.holds_if_inflows_drop_20pct ? "остаток не уходит в минус в этом сценарии" : "возможен минус"}.</p>
    </>}
    <h4>Где уходят деньги</h4>
    <p>Потери в год по оценке: {money(p.money.loss_per_year_minor)}. Возможности: {money(p.money.opportunity_per_year_minor)}.</p>
    <p>Это оценки отдельных направлений: они могут пересекаться и не складываются в общий эффект. Условия каждого варианта — в подробностях.</p>
    {!p.money.findings.length && <p>По имеющимся данным находок нет. Это не гарантия отсутствия лишних расходов.</p>}
    {p.money.findings.map((finding, i) => <details key={i}><summary>{finding.title} — {money(finding.amount_minor)} · {finding.certainty === "fact" ? "факт выписки" : "оценка"}</summary>
      <p>{finding.action}</p><ul>{finding.evidence.map((e, j) => <li key={j}>{e}</li>)}</ul>
    </details>)}
    <h4>Зависимость от клиентов</h4>
    <p>{p.clients.message}</p>
    {p.clients.at_risk.map((c, i) => <p key={i}>{c.name ?? "Клиент"}: {c.grade_label}; {Math.round(c.share * 100)}% выручки. {c.reasons.join(" ")}</p>)}
    {p.clients.stress.map((s, i) => <details key={i}><summary>{s.title}</summary><p>{s.text}</p><p>Основание сценария: {s.basis}</p></details>)}
    <h4>Следующие шаги</h4>
    {!p.actions.length && <p>Нет обоснованных действий по текущим данным.</p>}
    <ol>{p.actions.map((a, i) => <li key={i}><strong>{a.urgency === "now" ? "Сейчас" : a.urgency === "this_month" ? "В этом месяце" : "Позже"}: {a.title}</strong><p>{a.why}</p></li>)}</ol>
    {cash.suggestions.map((s, i) => <p key={i}>{s.title}. {s.details.join(" ")}</p>)}
    <details><summary>Источники и ограничения пульса</summary>
      <p>Прогноз {p.forecast_id}; модель {p.model_version}; вход {p.data_version}; метод {p.method_version}.</p>
      <ul>{[...new Set([...p.warnings, ...cash.assumptions, ...p.money.assumptions])].map((w, i) => <li key={i}>{w}</li>)}</ul>
    </details>
  </>;
}
