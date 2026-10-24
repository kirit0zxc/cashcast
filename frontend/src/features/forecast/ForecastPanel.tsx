import { type FormEvent } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money, probability, type Forecast } from "../../shared/api";
import { Explanations } from "./Explanations";
import { ForecastHistory } from "./ForecastHistory";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { useAccount } from "../../app/account-context";

// Состояние расчёта живёт в контроллере счёта: вкладка только показывает и управляет им.
export function ForecastPanel() {
  const { api, companyId, accountId, forecast: c } = useAccount();
  const canWrite = useCompanyCanWrite();
  function submit(event: FormEvent) { event.preventDefault(); c.run(); }
  return <section className="panel"><h2>Прогноз на 30 дней</h2>
    {canWrite && <form onSubmit={submit} className="row">
      <label>Дата среза<input type="date" disabled={c.working} required value={c.asOf}
        onChange={e => c.changeDate(e.target.value)} /></label>
      <button disabled={!accountId || c.working}>Рассчитать</button>
    </form>}
    <p>Используем сведения, известные на дату среза. Для выписки выберите её последний день.</p>
    {canWrite && <p>После сохранения данных в кабинете прогноз обновляется автоматически. Сохранённые расчёты остаются в истории.</p>}
    <p>На сегодняшнем срезе однозначные оплаты сверяются автоматически; неоднозначные подтверждайте вручную.</p>
    <ForecastHistory api={api} companyId={companyId} accountId={accountId} disabled={c.requesting} onOpen={c.open} />
    <ForecastState />
    {c.forecast.data?.status === "succeeded" && <><ForecastView forecast={c.forecast.data} />
      <Explanations api={api} forecastId={c.forecast.data.id} /></>}
  </section>;
}

// Общая строка состояния расчёта для вкладок, которые показывают выбранный прогноз.
export function ForecastState() {
  const { forecast: c } = useAccount();
  return <>
    {c.working && <p role="status">Задание: {c.job.data?.status ?? "отправляем"}. Ожидаем worker…</p>}
    {c.job.data?.status === "failed" && <p role="alert">Расчёт не выполнен: {c.job.data.error_code}</p>}
    {c.errors.map((e, i) => <p role="alert" key={i}>{e.message}</p>)}
    {c.forecast.data && c.forecast.data.status !== "succeeded" && <p role="status">
      Сохранённый расчёт: {c.forecast.data.status}. Открытие не создаёт новое задание.
      {c.selection.mode === "run" && c.selection.errorCode && ` Причина: ${c.selection.errorCode}`}
    </p>}
  </>;
}

// График хранит копейки; рубли используются только в подписях.
export function ForecastView({ forecast: f }: { forecast: Forecast }) {
  return <>
    <p>Модель: {f.model_version}. Начальный остаток: {money(f.opening_balance_minor)}.</p>
    <p data-testid="calculation-mode">{f.calculation?.mode === "incremental"
      ? f.calculation.reason === "observed_data_changed"
        ? "Частичное обновление: новые факты учтены, сохранённое состояние прогноза обновлено по изменениям."
        : "Частичное обновление: календарь пересчитан, история и траектории переиспользованы."
      : f.calculation ? "Полный расчёт: подготовлена история и рассчитан прогноз."
        : "Сохранённый прогноз: сведения о режиме расчёта отсутствуют."}</p>
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
      {f.calculation && <p>Причина: {f.calculation.reason}. Новых траекторий: {f.calculation.bootstrap_paths_generated}.
        {f.calculation.source_forecast_id && ` Источник истории: ${f.calculation.source_forecast_id}.`}</p>}
      {f.calculation?.categorized_transactions != null && <p>
        Операций обработано заново: {f.calculation.categorized_transactions}; переиспользовано: {f.calculation.reused_transactions}.
        Групп регулярностей проверено: {f.calculation.recurrence_buckets_recomputed}.
        Дневных сумм затронуто: {f.calculation.daily_aggregates_changed}.
      </p>}
      <div className="scroll"><table><thead><tr><th>Дата</th><th>Приход</th><th>Расход</th><th>Остаток p50</th>
        <th>Вероятность минуса за день</th></tr></thead><tbody>
        {f.points.map(p => <tr key={p.point_date}><td>{p.point_date}</td><td>{money(p.inflow_minor)}</td>
          <td>{money(p.outflow_minor)}</td><td>{money(p.balance_p50_minor)}</td><td>{probability(p.probability_negative)}</td></tr>)}
      </tbody></table></div>
    </details>
  </>;
}
