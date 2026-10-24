import { useState, type FormEvent } from "react";
import { money, probability, type Forecast } from "../../shared/api";
import { Explanations } from "./Explanations";
import { CashGapPanel } from "./CashGapPanel";
import { ForecastHistory } from "./ForecastHistory";
import { ProbabilityNotice } from "./ProbabilityNotice";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { useAccount } from "../../app/account-context";
import { Leaders, Tabs, dayMonth, dmy } from "../../ui/Blank";
import { Empty } from "../../ui/Empty";
import { SpecChart, bandAvailable } from "../../ui/SpecChart";

type Tab = "result" | "daily" | "history";

// Состояние расчёта живёт в контроллере счёта: вкладка только показывает и управляет им.
export function ForecastPanel() {
  const { api, companyId, accountId, forecast: c } = useAccount();
  const canWrite = useCompanyCanWrite();
  const [tab, setTab] = useState<Tab>("result");
  function submit(event: FormEvent) { event.preventDefault(); c.run(); }
  const f = c.forecast.data?.status === "succeeded" ? c.forecast.data : undefined;
  return <>
    <section className="toolbar">
      {canWrite ? <form onSubmit={submit} className="row">
        <label>Дата среза<input type="date" disabled={c.working} required value={c.asOf}
          onChange={e => c.changeDate(e.target.value)} /></label>
        <button disabled={!accountId || c.working}>Рассчитать</button>
      </form> : <span className="chip">срез {dmy(c.asOf)}</span>}
      <small>Новый расчёт в этом разделе охватывает 30 дней от выбранной даты. Период сохранённого расчёта указан в результате.</small>
    </section>
    <Tabs label="Прогноз" value={tab} onChange={setTab}
      items={[["result", "Результат"], ["daily", "По дням"], ["history", "История расчётов"]]} />
    {tab !== "history" && <ForecastState />}
    {tab !== "history" && !c.runId && !c.working && !c.loading && <Empty title="Расчёт не выбран"
      text={canWrite ? "Нажмите «Рассчитать» или откройте сохранённый расчёт во вкладке «История расчётов»."
        : "Откройте сохранённый расчёт во вкладке «История расчётов»."} />}
    {tab === "result" && f && <ForecastView forecast={f} />}
    {tab === "result" && f && <Explanations api={api} forecastId={f.id} />}
    {tab === "result" && f && <CashGapPanel key={f.id} api={api} forecastId={f.id} />}
    {tab === "daily" && f && <DailyTable forecast={f} />}
    {tab === "history" && <ForecastHistory api={api} companyId={companyId} accountId={accountId} disabled={c.requesting}
      onOpen={entry => { c.open(entry); setTab("result"); }} />}
  </>;
}

// Общая строка состояния расчёта для вкладок, которые показывают выбранный прогноз.
export function ForecastState() {
  const { forecast: c } = useAccount();
  return <>
    {c.stale && <p className="errors">Данные изменились — показанный прогноз устарел. Нажмите «Рассчитать».</p>}
    {c.working && <p role="status">{c.job.data?.status === "running" ? "Считаем прогноз…" : "Прогноз в очереди…"}</p>}
    {c.loading && !c.working && <p role="status">Загружаем сохранённый прогноз…</p>}
    {c.job.data?.status === "failed" && <p role="alert">Не удалось посчитать прогноз. Попробуйте ещё раз.</p>}
    {c.errors.map((e, i) => <p role="alert" key={i}>{e.message}</p>)}
    {c.forecast.data && c.forecast.data.status !== "succeeded" && <p role="status">
      {c.forecast.data.status === "failed" ? "Этот расчёт завершился с ошибкой." : "Этот расчёт ещё не готов."}
    </p>}
  </>;
}

function calculationText(f: Forecast) {
  return f.calculation?.mode === "incremental"
    ? f.calculation.reason === "observed_data_changed"
      ? "Частичное обновление: новые факты учтены."
      : "Частичное обновление: учтены изменения в планах."
    : "Полный расчёт.";
}

// График хранит копейки; рубли используются только в подписях.
export function ForecastView({ forecast: f }: { forecast: Forecast }) {
  const last = f.points.at(-1);
  return <div className="grid2 top0">
    <section className="panel">
      <span className="dots" aria-hidden="true">● ● ●</span>
      <span className="label">Остаток на счёте · {f.points.length} дн. от {dmy(f.as_of)}</span>
      <SpecChart points={f.points} label="Прогноз остатка: p10, медиана, p90" />
      <div className="legend">
        <span><i style={{ background: "var(--ink)" }} />медианный остаток</span>
        <span>{bandAvailable(f.points)
          ? <><i style={{ background: "radial-gradient(var(--ink) 30%, transparent 35%) 0 0/4px 4px" }} />возможный разброс</>
          : "разброс не оценён — данных мало"}</span>
      </div>
    </section>
    <section className="panel dash">
      <span className="label">Главное</span>
      <Leaders rows={[
        ["Начальный остаток", money(f.opening_balance_minor)],
        ["Первый день в минусе", f.risk.first_negative_date ? dayMonth(f.risk.first_negative_date)
          : f.risk.available ? "не прогнозируется" : "нет оценки"],
        ["Максимальный дефицит", f.risk.max_deficit_minor === null && !f.risk.first_negative_date
          ? "нет" : money(f.risk.max_deficit_minor)],
        ["Вероятность уйти в минус", f.risk.probability_any_negative === null ? "не оценивается" : probability(f.risk.probability_any_negative)],
        [last ? `На ${dmy(last.point_date)}` : "На конец прогноза", last ? money(last.balance_p50_minor) : "нет данных"],
      ]} />
      <p data-testid="calculation-mode" className="note">{calculationText(f)}</p>
      <ProbabilityNotice forecast={f} />
      {[...f.assumptions, ...f.data_warnings].length > 0 && <details><summary>Допущения и качество данных</summary>
        <ul className="plain">{[...f.assumptions, ...f.data_warnings].map((s, i) => <li key={i}>{s}</li>)}</ul></details>}
    </section>
  </div>;
}

function DailyTable({ forecast: f }: { forecast: Forecast }) {
  return <section className="panel flat">
    <ProbabilityNotice forecast={f} />
    <div className="panel-head"><div><h2>Дневные значения и происхождение расчёта</h2>
      <span className="label">Остаток, приход и расход по каждому дню</span></div></div>
    <details className="pad"><summary>Технические подробности расчёта</summary>
      <p className="note">Прогноз {f.id} · модель {f.model_version} · версия входа {f.data_version}</p>
      {f.calculation && <p className="note">Причина: {f.calculation.reason}. Новых траекторий: {f.calculation.bootstrap_paths_generated}.
        {f.calculation.source_forecast_id && ` Источник истории: ${f.calculation.source_forecast_id}.`}</p>}
      {f.calculation?.categorized_transactions != null && <p className="note">
        Операций обработано заново: {f.calculation.categorized_transactions}; переиспользовано: {f.calculation.reused_transactions}.
        Групп регулярностей проверено: {f.calculation.recurrence_buckets_recomputed}.
        Дневных сумм затронуто: {f.calculation.daily_aggregates_changed}.
      </p>}
    </details>
    <p className="note">p10 и p90 — нижняя и верхняя оценки модели. Остаток может выйти за этот диапазон;
      это не гарантированные границы. p50 — медианный остаток.</p>
    <div className="scroll"><table className="ops"><thead><tr><th>Дата</th><th className="num">Приход</th>
      <th className="num">Расход</th><th className="num">Нижняя оценка (p10)</th><th className="num">Медиана (p50)</th>
      <th className="num">Верхняя оценка (p90)</th><th className="num">Риск минуса</th></tr></thead><tbody>
      {f.points.map(p => <tr key={p.point_date}><td className="mono">{p.point_date}</td>
        <td className="num">{money(p.inflow_minor)}</td><td className="num">{money(p.outflow_minor)}</td>
        <td className="num">{money(p.balance_p10_minor)}</td>
        <td className={`num${p.balance_p50_minor < 0 ? " neg" : ""}`}><b>{money(p.balance_p50_minor)}</b></td>
        <td className="num">{money(p.balance_p90_minor)}</td>
        <td className="num">{probability(p.probability_negative)}</td></tr>)}
    </tbody></table></div>
  </section>;
}
