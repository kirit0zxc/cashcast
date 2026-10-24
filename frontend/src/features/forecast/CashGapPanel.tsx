import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { SpecLines } from "../../ui/SpecChart";
import { CashCastApi, money, rublesToMinor } from "../../shared/api";
import type { CashGapReport, GapAction, GapSummary } from "./cash-gaps";

const evidence: Record<string, string> = {
  observed: "Исходный остаток", planned: "План, ещё не оплата", estimated: "Оценка модели", scenario: "Гипотеза",
};

function GapCard({ summary, title }: { summary: GapSummary; title: string }) {
  return <section><h4>{title}</h4>
    <p>{summary.status === "gap" ? "Есть дефицит по медиане" : summary.status === "no_gap"
      ? "В этом горизонте медиана не уходит в минус" : "Недостаточно данных для вывода об отсутствии разрыва"}.</p>
    {summary.opening_already_negative && <p>На дату среза деньги уже в минусе. Это существующий дефицит.</p>}
    {summary.days_until_new_gap != null && <p>От даты среза до нового разрыва: {summary.days_until_new_gap} дн.</p>}
    {!!summary.required_reserve_minor && <p>Резерв на начало прогноза для покрытия дефицита:
      {" "}{money(summary.required_reserve_minor)}. Расчёт по медиане, без возврата этой суммы;
      для кредита отдельно проверьте дату возврата и стоимость.</p>}
    <p>Первый новый разрыв: {summary.first_new_gap_date ?? "не выявлен по медиане"}.
      Максимальная нехватка: {money(summary.max_deficit_minor)}. Дней в минусе: {summary.total_negative_days}.</p>
    {summary.episodes.length > 0 && <div className="scroll"><table className="ops"><thead><tr>
      <th>Тип</th><th>Начало</th><th>Длительность</th><th>Восстановление</th><th>Нехватка</th>
    </tr></thead><tbody>{summary.episodes.map(e => <tr key={e.first_negative_date}>
      <td>{e.kind === "existing" ? "Уже был" : "Новый"}</td><td>{e.first_negative_date}</td>
      <td>{e.duration_is_lower_bound ? "Не менее " : ""}{e.observed_days} дн.</td>
      <td>{e.recovery_date ?? "Не видно до конца горизонта"}</td><td>{money(e.max_deficit_minor)}</td>
    </tr>)}</tbody></table></div>}
  </section>;
}

export function CashGapPanel({ api, forecastId }: { api: CashCastApi; forecastId: string }) {
  const query = useQuery({ queryKey: ["cash-gaps", forecastId],
    queryFn: ({ signal }) => api.request<CashGapReport>(`/forecasts/${forecastId}/cash-gaps`, { signal }) });
  const preview = useMutation({ mutationFn: (actions: GapAction[]) =>
    api.post<CashGapReport>(`/forecasts/${forecastId}/cash-gap-preview`, { actions }) });
  const [kind, setKind] = useState("financing");
  const [flow, setFlow] = useState("");
  const [date, setDate] = useState("");
  const [repayment, setRepayment] = useState("");
  const [amount, setAmount] = useState("");
  const [cost, setCost] = useState("0");
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  // Любое редактирование убирает старое сравнение, чтобы не выдать его за новый результат.
  function edited() { preview.reset(); setError(""); }
  function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    try {
      const action: GapAction = kind === "financing" ? { kind, date, repayment_date: repayment,
        amount_minor: rublesToMinor(amount), cost_minor: rublesToMinor(cost, true) }
        : { kind: "delay", flow_id: flow, to_date: date, payment_delay_agreed: agreed };
      preview.mutate([action]);
    } catch (e) { setError(e instanceof Error ? e.message : "Проверьте суммы"); }
  }
  const report = preview.data ?? query.data;
  return <section className="panel" data-testid="cash-gap-panel"><h3>Кассовые разрывы</h3>
    {query.isPending && <p role="status">Загружаем сохранённый расчёт…</p>}
    {query.error && <p role="alert">{query.error.message}</p>}
    {report && <>
      <p>Срез {report.as_of}, горизонт до {report.horizon_end}. Остатки на конец дня.</p>
      <GapCard summary={report.base} title="Исходный прогноз" />
      <p>{report.probability_reason}</p>
      <details><summary>Из чего складывается минимум {report.causes_date}: {money(report.causes_balance_minor)}</summary>
        <p>Состав расчёта, а не доказательство причин. Планы могут не исполниться.</p>
        <div className="scroll"><table className="ops"><thead><tr><th>Дата</th><th>Компонент</th><th>Основание</th><th>Сумма</th></tr></thead>
          <tbody>{report.causes.map((c, i) => <tr key={i}><td>{c.date}</td><td>{c.label}</td>
            <td>{evidence[c.evidence] ?? c.evidence}</td><td>{money(c.amount_minor)}</td></tr>)}</tbody></table></div>
      </details>
      <h4>Проверить действие без изменения платежей</h4>
      <form onSubmit={submit} aria-label="Проверка кассового разрыва"><fieldset disabled={preview.isPending}>
        <label>Действие<select value={kind} onChange={e => { setKind(e.target.value); edited(); }}>
          <option value="financing">Дополнительное финансирование</option><option value="delay">Перенос платежа или поступления</option>
        </select></label>
        {kind === "delay" ? <>
          <label>Поток<select required value={flow} onChange={e => { setFlow(e.target.value); edited(); }}>
            <option value="">Выберите доступный поток</option>{report.flows.filter(f => f.delay_allowed).map(f =>
              <option key={f.id} value={f.id}>{f.date}: {f.label} ({money(f.amount_minor)})</option>)}
          </select></label>
          <label><input type="checkbox" checked={agreed} onChange={e => { setAgreed(e.target.checked); edited(); }} />
            Отсрочка расхода допустима в этой гипотезе (нужно согласовать с контрагентом)</label>
          <p>Задержка поступления проверяет ухудшение. Защищённые расходы и перенос за горизонт недоступны.</p>
        </> : <>
          <label>Сумма финансирования, ₽<input required inputMode="decimal" value={amount}
            onChange={e => { setAmount(e.target.value); edited(); }} /></label>
          <label>Полная стоимость финансирования, ₽<input required inputMode="decimal" value={cost}
            onChange={e => { setCost(e.target.value); edited(); }} /></label>
          <label>Дата возврата<input required type="date" value={repayment}
            onChange={e => { setRepayment(e.target.value); edited(); }} /></label>
        </>}
        <label>{kind === "delay" ? "Новая дата" : "Дата получения"}<input required type="date" value={date}
          max={report.horizon_end} onChange={e => { setDate(e.target.value); edited(); }} /></label>
        <button>Проверить действие</button>
      </fieldset></form>
      {(error || preview.error) && <p role="alert">{error || preview.error?.message}</p>}
      {preview.isPending && <p role="status">Сравниваем с исходным прогнозом…</p>}
      {preview.data && <div data-testid="cash-gap-comparison">
        <GapCard summary={report.preview} title="После гипотетического действия" />
        <p>Снижение максимальной нехватки: {money(report.improvement_minor)}.
          Стоимость финансирования: {money(report.financing_cost_minor)}.
          Долг за горизонтом: {money(report.debt_beyond_horizon_minor)}.</p>
        <p>Платежи не изменены. Результат относится только к указанным датам и суммам.</p>
        <div>
          <SpecLines dates={report.points.map(p => p.date)} label="Сравнение остатков до и после действия"
            series={[
              { name: "База", values: report.points.map(p => p.base_minor), style: "ink" },
              { name: "Гипотеза", values: report.points.map(p => p.preview_minor), style: "dash" },
            ]} />
          <div className="legend"><span>Сплошная — база</span><span>Пунктир — гипотеза</span></div>
        </div>
        <button type="button" onClick={() => preview.reset()}>Сбросить сравнение</button>
      </div>}
      <details><summary>Ограничения и качество данных: {report.quality_mode}</summary>
        <ul>{report.warnings.map(w => <li key={w}>{w}</li>)}</ul>
      </details>
    </>}
  </section>;
}
