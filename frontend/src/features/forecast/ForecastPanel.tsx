import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CashCastApi, money, probability, type Accepted, type Forecast, type Job } from "../../shared/api";
import { Explanations } from "./Explanations";
import { ForecastHistory } from "./ForecastHistory";
import { ScenarioPanel } from "./ScenarioPanel";
import { useCompanyCanWrite } from "../../shared/company-permissions";

export function ForecastPanel({ api, companyId, accountId, initialDate, autoRun, onDateChange }: {
  api: CashCastApi; companyId: string; accountId: string; initialDate: string;
  autoRun: boolean; onDateChange: (date: string) => void;
}) {
  const canWrite = useCompanyCanWrite();
  const [asOf, setAsOf] = useState(initialDate);
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const [saved, setSaved] = useState<{ id: string; job_id: string | null; error_code?: string | null } | null>(null);
  const runId = saved?.id ?? accepted?.forecast_run_id;
  const jobId = saved ? saved.job_id : accepted?.job_id;
  const cache = useQueryClient();
  const mutation = useMutation({
    mutationFn: (requestedDate: string) => api.post<Accepted>(`/companies/${companyId}/forecasts`, {
      account_id: accountId, as_of: requestedDate, horizon_days: 30,
    }), onSuccess: async data => {
      setSaved(null);
      setAccepted(data);
      // Enqueue может выполнить auto-reconcile; job остаётся в этом компоненте.
      await Promise.all([
        // Явный recovery может вернуть тот же ID после cached failed.
        cache.invalidateQueries({ queryKey: ["job", data.job_id] }),
        cache.invalidateQueries({ queryKey: ["forecast", data.forecast_run_id] }),
        cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] }),
        cache.invalidateQueries({ queryKey: ["plan-fact", companyId, accountId] }),
        cache.invalidateQueries({ queryKey: ["forecast-history", companyId, accountId] }),
      ]);
    },
  });
  const automaticSent = useRef(false);
  const { mutate } = mutation;
  useEffect(() => {
    if (!canWrite || !autoRun || automaticSent.current) return;
    // StrictMode сначала снимает подписку mutation observer и повторяет setup.
    // Отменённый setup не отправляет POST; рабочий запускается после переподписки.
    let active = true;
    queueMicrotask(() => {
      if (!active || automaticSent.current) return;
      automaticSent.current = true;
      mutate(initialDate);
    });
    return () => { active = false; };
  }, [canWrite, autoRun, initialDate, mutate]);
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.request<Job>(`/jobs/${jobId}`, { signal }),
    enabled: !!jobId,
    refetchInterval: query => ["succeeded", "failed"].includes(query.state.data?.status ?? "") ? false : 1500,
  });
  const forecast = useQuery({
    queryKey: ["forecast", runId],
    queryFn: ({ signal }) => api.request<Forecast>(`/forecasts/${runId}`, { signal }),
    enabled: !!runId && (!jobId || job.error !== null || ["succeeded", "failed"].includes(job.data?.status ?? "")),
  });
  const working = mutation.isPending || (!!jobId && !job.error
    && !["succeeded", "failed"].includes(job.data?.status ?? ""));
  function submit(event: FormEvent) {
    event.preventDefault(); if (!canWrite) return; automaticSent.current = true;
    setSaved(null); setAccepted(null); mutation.mutate(asOf);
  }
  return <section className="panel"><h2>2. Прогноз на 30 дней</h2>
    {canWrite && <form onSubmit={submit} className="row">
      <label>Дата среза<input type="date" disabled={working} required value={asOf} onChange={e => {
        setAsOf(e.target.value); onDateChange(e.target.value);
        setSaved(null); setAccepted(null); mutation.reset();
      }} /></label>
      <button disabled={!accountId || working}>Рассчитать</button>
    </form>}
    <p>Используем сведения, известные на дату среза. Для выписки выберите её последний день.</p>
    {canWrite && <p>После сохранения данных в кабинете прогноз обновляется автоматически. Сохранённые расчёты остаются в истории.</p>}
    <p>На сегодняшнем срезе однозначные оплаты сверяются автоматически; неоднозначные подтверждайте вручную.</p>
    <ForecastHistory api={api} companyId={companyId} accountId={accountId} disabled={mutation.isPending}
      onOpen={entry => {
        mutation.reset(); setAccepted(null); setAsOf(entry.as_of); onDateChange(entry.as_of);
        setSaved({ id: entry.id, job_id: entry.job_id, error_code: entry.error_code });
      }} />
    {working && <p role="status">Задание: {job.data?.status ?? "отправляем"}. Ожидаем worker…</p>}
    {job.data?.status === "failed" && <p role="alert">Расчёт не выполнен: {job.data.error_code}</p>}
    {[mutation.error, job.error, forecast.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
    {forecast.data && forecast.data.status !== "succeeded" && <p role="status">
      Сохранённый расчёт: {forecast.data.status}. Открытие не создаёт новое задание.
      {saved?.error_code && ` Причина: ${saved.error_code}`}
    </p>}
    {forecast.data?.status === "succeeded" && <><ForecastView forecast={forecast.data} />
      <Explanations api={api} forecastId={forecast.data.id} />
      {forecast.data.base_forecast_id ? <button type="button" onClick={() => {
        setAccepted(null); setSaved({ id: forecast.data!.base_forecast_id!, job_id: null });
      }}>Открыть исходный прогноз</button> : canWrite && <ScenarioPanel key={forecast.data.id} api={api} base={forecast.data} />}</>}
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
