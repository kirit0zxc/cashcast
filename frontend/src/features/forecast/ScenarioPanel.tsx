import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { SpecLines } from "../../ui/SpecChart";
import { CashCastApi, money, probability, rublesToMinor,
  type Accepted, type Explanation, type Forecast, type Job } from "../../shared/api";

interface Comparison {
  base_forecast_id: string; scenario_forecast_id: string;
  points: { point_date: string; base_balance_p50_minor: number; scenario_balance_p50_minor: number; delta_balance_minor: number }[];
  risk: { base: Forecast["risk"]; scenario: Forecast["risk"] };
}

type ScenarioKind = "add_expense" | "delay_event" | "reduce_irregular_inflow" | "increase_recurring";

const KIND_TITLES: Record<ScenarioKind, string> = { add_expense: "Дополнительный расход", delay_event: "Задержка поступления",
  reduce_irregular_inflow: "Снижение нерегулярной выручки", increase_recurring: "Рост регулярного списания" };

// Цели берём из сохранённого расчёта: сегодняшние планы могут отличаться от его снимка.
export function ScenarioPanel({ api, base }: { api: CashCastApi; base: Forecast }) {
  const canWrite = useCompanyCanWrite();
  const cache = useQueryClient();
  const [kind, setKind] = useState<ScenarioKind>("add_expense");
  const [amount, setAmount] = useState("1000");
  const [date, setDate] = useState(base.points[0]?.point_date ?? "");
  const [percent, setPercent] = useState("20");
  const [shift, setShift] = useState("7");
  const [target, setTarget] = useState("");
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const explanations = useQuery({ queryKey: ["explanations", base.id],
    queryFn: ({ signal }) => api.request<Explanation>(`/forecasts/${base.id}/explanations`, { signal }) });
  const targetKind = kind === "delay_event" ? "planned" : "recurrence";
  const targets = [...new Map((explanations.data?.items ?? []).filter(item =>
    item.kind === targetKind && item.source_ref && item.detail.direction === (kind === "delay_event" ? "in" : "out"),
  ).map(item => [item.source_ref!, item])).values()];
  const selectedTarget = targets.some(item => item.source_ref === target) ? target : targets[0]?.source_ref ?? "";
  const needsTarget = kind === "delay_event" || kind === "increase_recurring";
  const mutation = useMutation({ mutationFn: () => {
    let change: object;
    if (kind === "add_expense") change = { kind, amount_minor: rublesToMinor(amount), on_date: date };
    else if (kind === "delay_event") {
      const days = Number(shift);
      if (!selectedTarget || !Number.isInteger(days) || days < 1 || days > 3650) {
        throw new Error("Выберите поступление и задержку от1 до3650дней");
      }
      change = { kind, target_id: selectedTarget, shift_days: days };
    } else {
      const value = Number(percent);
      if (!percent.trim() || !Number.isFinite(value) || value < 0 || value > 100) {
        throw new Error("Укажите процент от0 до100");
      }
      if (kind === "increase_recurring" && !selectedTarget) throw new Error("В базе нет регулярного списания");
      change = { kind, factor: kind === "reduce_irregular_inflow" ? 1 - value / 100 : 1 + value / 100,
        ...(kind === "increase_recurring" ? { target_id: selectedTarget } : {}) };
    }
    return api.post<Accepted>(`/forecasts/${base.id}/scenarios`, { changes: [change] });
  }, onSuccess: async value => {
    setAccepted(value);
    await Promise.all([
      cache.invalidateQueries({ queryKey: ["job", value.job_id] }),
      cache.invalidateQueries({ queryKey: ["comparison", value.forecast_run_id] }),
      cache.invalidateQueries({ queryKey: ["forecast-history"] }),
    ]);
  } });
  const job = useQuery({ queryKey: ["job", accepted?.job_id],
    queryFn: ({ signal }) => api.request<Job>(`/jobs/${accepted!.job_id}`, { signal }), enabled: !!accepted,
    refetchInterval: query => ["succeeded", "failed"].includes(query.state.data?.status ?? "") ? false : 1500 });
  const comparison = useQuery({ queryKey: ["comparison", accepted?.forecast_run_id],
    queryFn: ({ signal }) => api.request<Comparison>(`/forecasts/${accepted!.forecast_run_id}/comparison`, { signal }),
    enabled: job.data?.status === "succeeded" });
  const pending = mutation.isPending || (!!accepted && !job.error && !["succeeded", "failed"].includes(job.data?.status ?? ""));
  function resetResult() { setAccepted(null); mutation.reset(); }
  function submit(event: FormEvent) { event.preventDefault(); if (!canWrite) return; setAccepted(null); mutation.mutate(); }
  const last = comparison.data?.points.at(-1);
  if (!canWrite) return null;
  return <>
    <section className="panel dash"><span className="label">Изменение · {KIND_TITLES[kind]}</span>
      <form className="row" onSubmit={submit}>
      <label>Вид сценария<select disabled={pending} value={kind} onChange={e => {
        setKind(e.target.value as ScenarioKind); setTarget(""); resetResult();
      }}><option value="add_expense">Дополнительный расход</option>
        <option value="delay_event">Задержка поступления</option>
        <option value="reduce_irregular_inflow">Снижение нерегулярной выручки</option>
        <option value="increase_recurring">Рост регулярного списания</option></select></label>
      {kind === "add_expense" && <>
        <label>Дополнительный расход, ₽<input disabled={pending} inputMode="decimal" required value={amount}
          onChange={e => { setAmount(e.target.value); resetResult(); }} /></label>
        <label>Дата расхода<input disabled={pending} type="date" required value={date} min={base.points[0]?.point_date}
          max={base.points.at(-1)?.point_date} onChange={e => { setDate(e.target.value); resetResult(); }} /></label>
      </>}
      {needsTarget && <label>Платёж из базового прогноза<select disabled={pending} required value={selectedTarget}
        onChange={e => { setTarget(e.target.value); resetResult(); }}>
        {targets.length === 0 && <option value="">Нет подходящих платежей</option>}
        {targets.map(item => <option key={item.source_ref} value={item.source_ref!}>
          {item.detail.date}: {money(item.amount_minor)} · {item.source_ref!.slice(0, 8)}
        </option>)}
      </select></label>}
      {kind === "delay_event" && <label>Задержка, дней<input disabled={pending} type="number" required min={1} max={3650}
        value={shift} onChange={e => { setShift(e.target.value); resetResult(); }} /></label>}
      {(kind === "reduce_irregular_inflow" || kind === "increase_recurring") && <label>Изменение, %
        <input disabled={pending} type="number" required min={0} max={100} step="any" value={percent}
          onChange={e => { setPercent(e.target.value); resetResult(); }} /></label>}
      <button disabled={pending || (needsTarget && !selectedTarget)}>Проверить сценарий</button>
    </form>
    {needsTarget && explanations.isPending && <p role="status">Получаем цели из базового расчёта…</p>}
    {needsTarget && explanations.error && <p role="alert">{explanations.error.message}</p>}
    {needsTarget && explanations.data && targets.length === 0 && <p className="errors">
      {kind === "delay_event" ? "В сохранённой базе нет будущего поступления. Добавьте план и пересчитайте базу."
        : "В сохранённой базе нет регулярного списания. Нужна история с подтверждёнными повторами."}</p>}
    <small>Сценарий использует сохранённую базу. Он не меняет выписку и реальные обязательства.</small>
    {pending && <p role="status">Считаем сценарий по сохранённой базе…</p>}
    {[mutation.error, job.error, comparison.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
    {job.data?.status === "failed" && <p role="alert">Ошибка сценария: {job.data.error_code}</p>}
    </section>
    {comparison.data && last && <section data-testid="scenario-comparison">
      <div className="kpis">
        <div className="kpi"><span className="label">Изменение к концу горизонта</span>
          <div className={`v${last.delta_balance_minor < 0 ? " neg" : ""}`}>{money(last.delta_balance_minor)}</div>
          <div className="s">сценарий минус база, по медиане</div></div>
        <div className="kpi"><span className="label">База</span><div className="v">{money(last.base_balance_p50_minor)}</div>
          <div className="s">{last.point_date}</div></div>
        <div className="kpi"><span className="label">Сценарий</span><div className="v">{money(last.scenario_balance_p50_minor)}</div>
          <div className="s">{last.point_date}</div></div>
        <div className={`kpi${comparison.data.risk.scenario.probability_any_negative === null ? " na" : ""}`}>
          <span className="label">Вероятность минуса</span>
          <div className="v">{probability(comparison.data.risk.base.probability_any_negative)} → {probability(comparison.data.risk.scenario.probability_any_negative)}</div>
          <div className="s">модельная, не откалибрована; база → сценарий</div></div>
      </div>
      <div className="panel" style={{ marginTop: 24 }}>
        <span className="label">Медиана остатка · база и сценарий</span>
        <SpecLines label="Сравнение: база и сценарий" dates={comparison.data.points.map(p => p.point_date)} series={[
          { name: "сценарий", values: comparison.data.points.map(p => p.scenario_balance_p50_minor), style: "ink" },
          { name: "база", values: comparison.data.points.map(p => p.base_balance_p50_minor), style: "dash" },
        ]} />
        <div className="legend"><span><i style={{ background: "var(--ink)" }} />сценарий</span>
          <span><i style={{ background: "repeating-linear-gradient(90deg, var(--ink) 0 5px, transparent 5px 8px)" }} />база</span></div>
        <details><summary>Дневное сравнение</summary><div className="scroll"><table className="ops"><thead><tr>
          <th>Дата</th><th className="num">База</th><th className="num">Сценарий</th><th className="num">Изменение</th></tr></thead><tbody>
          {comparison.data.points.map(p => <tr key={p.point_date}><td className="mono">{p.point_date}</td>
            <td className="num">{money(p.base_balance_p50_minor)}</td><td className="num">{money(p.scenario_balance_p50_minor)}</td>
            <td className={`num${p.delta_balance_minor < 0 ? " neg" : ""}`}>{money(p.delta_balance_minor)}</td></tr>)}
        </tbody></table></div></details>
      </div>
    </section>}
  </>;
}
