import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CashCastApi, money, probability, type Accepted, type Forecast, type Job } from "../../shared/api";
import { Explanations } from "./Explanations";

export function ForecastPanel({ api, companyId, accountId, initialDate }: {
  api: CashCastApi; companyId: string; accountId: string; initialDate: string;
}) {
  const [asOf, setAsOf] = useState(initialDate);
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const mutation = useMutation({
    mutationFn: () => api.post<Accepted>(`/companies/${companyId}/forecasts`, {
      account_id: accountId, as_of: asOf, horizon_days: 30,
    }), onSuccess: data => setAccepted(data),
  });
  const job = useQuery({
    queryKey: ["job", accepted?.job_id],
    queryFn: ({ signal }) => api.request<Job>(`/jobs/${accepted!.job_id}`, { signal }),
    enabled: !!accepted,
    refetchInterval: query => ["succeeded", "failed"].includes(query.state.data?.status ?? "") ? false : 1500,
  });
  const forecast = useQuery({
    queryKey: ["forecast", accepted?.forecast_run_id],
    queryFn: ({ signal }) => api.request<Forecast>(`/forecasts/${accepted!.forecast_run_id}`, { signal }),
    enabled: job.data?.status === "succeeded",
  });
  const working = mutation.isPending || (!!accepted && !job.error
    && !["succeeded", "failed"].includes(job.data?.status ?? ""));
  function submit(event: FormEvent) { event.preventDefault(); setAccepted(null); mutation.mutate(); }
  return <section className="panel"><h2>2. Прогноз на 30 дней</h2>
    <form onSubmit={submit} className="row">
      <label>Дата среза<input type="date" required value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
      <button disabled={!accountId || working}>Рассчитать</button>
    </form>
    <p>Используем сведения, известные на дату среза. Для выписки выберите её последний день.</p>
    {working && <p role="status">Задание: {job.data?.status ?? "отправляем"}. Ожидаем worker…</p>}
    {job.data?.status === "failed" && <p role="alert">Расчёт не выполнен: {job.data.error_code}</p>}
    {[mutation.error, job.error, forecast.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
    {forecast.data && <><ForecastView forecast={forecast.data} />
      <Explanations api={api} forecastId={forecast.data.id} /></>}
  </section>;
}

// График хранит копейки; рубли используются только в подписях.
function ForecastView({ forecast: f }: { forecast: Forecast }) {
  return <>
    <p>Модель: {f.model_version}. Начальный остаток: {money(f.opening_balance_minor)}.</p>
    <p>Первый минус по медиане: {f.risk.first_negative_date ?? (f.risk.available ? "не прогнозируется" : "нет оценки")}.
      Максимальный дефицит: {money(f.risk.max_deficit_minor)}.
      Модельная вероятность минуса за горизонт: {probability(f.risk.probability_any_negative)}.</p>
    {!f.risk.available && <p>Оценка риска недоступна: смотрите ограничения данных.</p>}
    <div className="chart" role="img" aria-label="Прогноз остатка: p10, медиана, p90">
      <ResponsiveContainer width="100%" height={280}><LineChart data={f.points}>
        <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="point_date" />
        <YAxis width={100} tickFormatter={v => money(Number(v))} />
        <Tooltip formatter={v => money(Number(v))} />
        <Line dataKey="balance_p10_minor" name="p10" stroke="#8c99ab" dot={false} />
        <Line dataKey="balance_p50_minor" name="Медиана" stroke="#315d9d" dot={false} />
        <Line dataKey="balance_p90_minor" name="p90" stroke="#657b96" dot={false} />
      </LineChart></ResponsiveContainer>
    </div>
    <ul>{[...f.assumptions, ...f.data_warnings].map((s, i) => <li key={i}>{s}</li>)}</ul>
    <details><summary>Дневные значения и происхождение расчёта</summary>
      <p>Прогноз {f.id}. Версия входа {f.data_version}.</p>
      <div className="scroll"><table><thead><tr><th>Дата</th><th>Приход</th><th>Расход</th><th>Остаток p50</th>
        <th>Вероятность минуса за день</th></tr></thead><tbody>
        {f.points.map(p => <tr key={p.point_date}><td>{p.point_date}</td><td>{money(p.inflow_minor)}</td>
          <td>{money(p.outflow_minor)}</td><td>{money(p.balance_p50_minor)}</td><td>{probability(p.probability_negative)}</td></tr>)}
      </tbody></table></div>
    </details>
  </>;
}
