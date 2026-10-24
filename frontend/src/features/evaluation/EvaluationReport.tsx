import { probability, money } from "../../shared/api";
import type { Classification, EvaluationPoint, EvaluationReport as Report, Metric } from "./types";

const titles: Record<string, string> = { accuracy: "Accuracy", precision: "Precision", recall: "Recall", f1: "F1",
  brier: "Brier score", roc_auc: "ROC-AUC", average_precision: "Average Precision" };

function Value({ metric }: { metric: Metric }) {
  return <span title={metric.unavailable_reason ?? undefined}>{metric.value === null
    ? `Недоступно: ${metric.unavailable_reason}` : new Intl.NumberFormat("ru-RU", { maximumSignificantDigits: 6 }).format(metric.value)}</span>;
}

function Matrix({ data, title }: { data: Classification; title: string }) {
  const c = data.confusion_matrix;
  return <section className="panel"><h3>{title}</h3><p>Случаев: {data.n} · Порог: {data.threshold}</p>
    <table><thead><tr><th>Факт / прогноз</th><th>Минус</th><th>Нет минуса</th></tr></thead>
      <tbody><tr><th>Минус</th><td>TP: {c.tp}</td><td>FN: {c.fn}</td></tr>
        <tr><th>Нет минуса</th><td>FP: {c.fp}</td><td>TN: {c.tn}</td></tr></tbody></table>
    <dl className="leaders">{Object.entries(data.metrics).map(([key, metric]) => <div key={key}>
      <dt>{titles[key] ?? key}</dt><i /><dd><Value metric={metric} /></dd></div>)}</dl>
  </section>;
}

function ComparisonChart({ points }: { points: EvaluationPoint[] }) {
  const values = points.flatMap(p => [p.balance_p10_minor, p.balance_p90_minor, p.actual_balance_minor ?? 0]);
  const low = Math.min(0, ...values), high = Math.max(0, ...values), span = Math.max(1, high - low);
  const x = (index: number) => 80 + index * 740 / Math.max(1, points.length - 1);
  const y = (amount: number) => 225 - (amount - low) * 195 / span;
  return <><svg viewBox="0 0 900 275" role="img" aria-label="График прогноза и фактического остатка" style={{ width: "100%", minHeight: 180 }}>
    <line x1="80" x2="820" y1={y(0)} y2={y(0)} stroke="#aab0b0" />
    <text x="0" y="20" fontSize="12" fill="currentColor">{money(high)}</text>
    <text x="0" y="240" fontSize="12" fill="currentColor">{money(low)}</text>
    {(["balance_p10_minor", "balance_p90_minor", "balance_p50_minor", "actual_balance_minor"] as const).map(key => {
      const color = key === "actual_balance_minor" ? "#d26630" : key === "balance_p50_minor" ? "#2679b9" : "#99afbf";
      // Разрываем линии на неизвестном факте, не изображаем интерполяцию как наблюдение.
      return <g key={key}>{points.map((point, i) => {
        const amount = point[key], previous = i ? points[i - 1][key] : null;
        if (amount === null) return null;
        return <g key={point.date}><circle cx={x(i)} cy={y(amount)} r="2" fill={color}>
          <title>{point.date}: {money(amount)}</title></circle>
          {previous !== null && <line x1={x(i - 1)} y1={y(previous)} x2={x(i)} y2={y(amount)} stroke={color}
            strokeWidth="2" strokeDasharray={key === "balance_p10_minor" || key === "balance_p90_minor" ? "5 4" : undefined} />}</g>;
      })}</g>;
    })}
    <text x="80" y="265" fontSize="12" fill="currentColor">{points[0]?.date}</text>
    <text x="750" y="265" fontSize="12" fill="currentColor">{points.at(-1)?.date}</text>
  </svg><p className="note">Синий — прогноз p50; оранжевый — факт; пунктир — p10/p90. Диапазон не является гарантией.</p></>;
}

export function EvaluationReport({ report: r, id }: { report: Report; id: string }) {
  return <div data-testid="evaluation-report">
    <section className="panel"><h2>Результат проверки</h2><p>Модель: <strong>{r.model_version}</strong> · seed {r.config.seed}</p>
      <p>Нормализованный набор: <code style={{ overflowWrap: "anywhere" }}>{r.dataset_sha256}</code></p>
      <p>Оценка по истории операций без плановых событий. Вероятности не откалиброваны.</p>
      <div className="row"><a href={`/api/v1/evaluations/${id}/report?format=html`} download>Скачать HTML с графиками</a>
        <a href={`/api/v1/evaluations/${id}/report?format=json`} download>Скачать полный JSON</a></div>
    </section>
    <section className="panel"><h3>Ошибки денежных величин</h3><div style={{ overflowX: "auto" }}>
      <table><thead><tr><th>Величина</th><th>Дней</th><th>MAE, ₽</th><th>MSE, ₽²</th><th>RMSE, ₽</th></tr></thead>
        <tbody>{Object.entries(r.regression).map(([key, value]) => <tr key={key}>
          <th>{{ balance: "Остаток", inflow: "Поступления", outflow: "Списания" }[key]}</th><td>{value.n}</td>
          <td><Value metric={value.mae} /></td><td><Value metric={value.mse} /></td><td><Value metric={value.rmse} /></td>
        </tr>)}</tbody></table></div><p>Покрытие диапазона p10–p90 (доля): <Value metric={r.interval_coverage} /></p></section>
    <Matrix data={r.daily_median_negative} title="Ежедневный минус по медиане" />
    <Matrix data={r.daily_probability_negative} title="Ежедневный минус по вероятности" />
    <Matrix data={r.horizon_new_gap} title="Новый минус за весь горизонт" />
    {r.windows.map(window => <section className="panel" key={window.index}><h3>Окно {window.index}: срез {window.as_of}</h3>
      {window.status === "skipped" ? <p>Пропущено: {window.reason}</p> : <>
        <ComparisonChart points={window.points} /><p>Вероятность минуса за горизонт: {probability(window.probability_any_negative ?? null)}</p>
        <ul>{window.warnings?.map((warning, i) => <li key={i}>{warning}</li>)}</ul>
        <details><summary>Дневные значения и компоненты расчёта</summary><div style={{ overflowX: "auto" }}>
          <table><thead><tr><th>Дата</th><th>Прогноз ₽</th><th>Факт ₽</th><th>Источник факта</th><th>P(минус)</th><th>Компоненты, коп.</th></tr></thead>
            <tbody>{window.points.map(p => <tr key={p.date}><td>{p.date}</td><td>{money(p.balance_p50_minor)}</td>
              <td>{p.actual_balance_minor === null ? "Нет факта" : money(p.actual_balance_minor)}</td>
              <td>{{ observed: "Наблюдаемый", reconstructed: "Восстановлен по полной выписке", missing: "Нет" }[p.balance_source]}</td>
              <td>{probability(p.probability_negative)}</td><td><code>{JSON.stringify(p.components)}</code></td></tr>)}</tbody></table>
        </div></details></>}
    </section>)}
    <section className="panel"><h3>Пошаговый журнал вычислений</h3><ol>{r.trace.map((item, i) => <li key={i}>{item.message}</li>)}</ol></section>
    <section className="panel"><h3>Границы результата</h3><ul>{r.limitations.map(item => <li key={item}>{item}</li>)}</ul></section>
  </div>;
}
