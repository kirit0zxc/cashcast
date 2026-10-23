import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CashCastApi, money, probability, rublesToMinor, type Accepted, type Forecast, type Job } from "../../shared/api";

interface Comparison {
  base_forecast_id: string; scenario_forecast_id: string;
  points: { point_date: string; base_balance_p50_minor: number; scenario_balance_p50_minor: number; delta_balance_minor: number }[];
  risk: { base: Forecast["risk"]; scenario: Forecast["risk"] };
}

// Минимальный сценарий демо: гипотетический расход не меняет ни факт, ни исходный прогноз.
export function ScenarioPanel({ api, base }: { api: CashCastApi; base: Forecast }) {
  const [amount, setAmount] = useState("1000");
  const [date, setDate] = useState(base.points[0]?.point_date ?? "");
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const mutation = useMutation({ mutationFn: () => {
    const minor = rublesToMinor(amount);
    return api.post<Accepted>(`/forecasts/${base.id}/scenarios`, {
      changes: [{ kind: "add_expense", amount_minor: minor, on_date: date }],
    });
  }, onSuccess: value => setAccepted(value) });
  const job = useQuery({ queryKey: ["job", accepted?.job_id],
    queryFn: ({ signal }) => api.request<Job>(`/jobs/${accepted!.job_id}`, { signal }), enabled: !!accepted,
    refetchInterval: query => ["succeeded", "failed"].includes(query.state.data?.status ?? "") ? false : 1500 });
  const comparison = useQuery({ queryKey: ["comparison", accepted?.forecast_run_id],
    queryFn: ({ signal }) => api.request<Comparison>(`/forecasts/${accepted!.forecast_run_id}/comparison`, { signal }),
    enabled: job.data?.status === "succeeded" });
  const pending = mutation.isPending || (!!accepted && !job.error && !["succeeded", "failed"].includes(job.data?.status ?? ""));
  function submit(event: FormEvent) { event.preventDefault(); setAccepted(null); mutation.mutate(); }
  const last = comparison.data?.points.at(-1);
  return <section><h3>3. Что, если добавить расход?</h3>
    <form className="row" onSubmit={submit}>
      <label>Дополнительный расход, ₽<input inputMode="decimal" required value={amount} onChange={e => setAmount(e.target.value)} /></label>
      <label>Дата расхода<input type="date" required value={date} min={base.points[0]?.point_date}
        max={base.points.at(-1)?.point_date} onChange={e => setDate(e.target.value)} /></label>
      <button disabled={pending}>Проверить сценарий</button>
    </form>
    {pending && <p role="status">Считаем сценарий по сохранённой базе…</p>}
    {[mutation.error, job.error, comparison.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
    {job.data?.status === "failed" && <p role="alert">Ошибка сценария: {job.data.error_code}</p>}
    {comparison.data && last && <div data-testid="scenario-comparison">
      <p>Изменение остатка в конце горизонта: <strong>{money(last.delta_balance_minor)}</strong>.</p>
      <p>База: {money(last.base_balance_p50_minor)}. Сценарий: {money(last.scenario_balance_p50_minor)}.</p>
      <p>Модельная вероятность минуса: {probability(comparison.data.risk.base.probability_any_negative)} → {probability(comparison.data.risk.scenario.probability_any_negative)}.</p>
      <details><summary>Дневное сравнение</summary><div className="scroll"><table><thead><tr>
        <th>Дата</th><th>База</th><th>Сценарий</th><th>Изменение</th></tr></thead><tbody>
        {comparison.data.points.map(p => <tr key={p.point_date}><td>{p.point_date}</td>
          <td>{money(p.base_balance_p50_minor)}</td><td>{money(p.scenario_balance_p50_minor)}</td>
          <td>{money(p.delta_balance_minor)}</td></tr>)}
      </tbody></table></div></details>
    </div>}
  </section>;
}
