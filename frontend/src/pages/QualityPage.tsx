import { useQuery } from "@tanstack/react-query";
import { useAccount } from "../app/account-context";
import { Link } from "../app/router";
import { Leaders } from "../ui/Blank";
import { Empty } from "../ui/Empty";

interface Metric { value: number | null; definition: string; unavailable_reason?: string | null }
interface Cohort {
  name: string; windows: number; accounts: number; positive_windows: number; positive_accounts: number;
  threshold: number; confusion_matrix: { tp: number; fp: number; fn: number; tn: number }; metrics: Record<string, Metric>;
}
interface QualityReport {
  evaluated_model: string; horizon_days: number; label_definition: string; production_activated: false;
  applies_to_current_forecast: false; cohorts: Cohort[]; release: { allowed?: boolean; reasons?: string[] };
  limitations: string[];
}

const COHORTS: Record<string, string> = {
  validation: "Подбор настроек", test_development_accounts: "Проверка: знакомые счета",
  test_unseen_accounts: "Проверка: новые счета, которых модель не видела",
};
const RELEASE: Record<string, string> = {
  no_candidate_passes_selection: "ни один вариант модели не прошёл заранее заданные критерии",
  no_target_sme_validation: "нет проверки именно на малом бизнесе",
  test_previously_inspected: "проверочный период уже изучался раньше — нужен новый независимый",
};
const pct = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v * 100)}%`;

// Человеческий вид публичного отчёта /models/quality. Все числа — из ответа API.
// Отчёт про исследовательскую модель, а не про прогноз этого счёта: так и пишем.
export function QualityPage() {
  const { api } = useAccount();
  const query = useQuery({ queryKey: ["model-quality"], staleTime: 10 * 60_000, retry: false,
    queryFn: ({ signal }) => api.request<QualityReport>("/models/quality", { signal }) });
  const r = query.data;
  if (query.isPending) return <p role="status">Загружаем отчёт…</p>;
  if (query.error || !r) return <Empty title="Отчёт недоступен" text={query.error?.message} />;
  const unseen = r.cohorts.find(c => c.name === "test_unseen_accounts") ?? r.cohorts.at(-1)!;
  const m = unseen.confusion_matrix;
  const alerts = m.tp + m.fp;
  return <div className="quality">
    <section className="gap-banner tone-unknown">
      <div>
        <span className="label">Коротко</span>
        <b>Мы проверили, можно ли заранее предсказать кассовый разрыв, на реальных банковских данных</b>
        <p>На новых счетах модель заметила <strong>{m.tp} из {m.tp + m.fn}</strong> настоящих разрывов.
          Из {alerts} её предупреждений верными оказались {m.tp}, остальные {m.fp} — ложные тревоги.
          {r.release.allowed === false && " Это пока недостаточно, поэтому в ваш прогноз эта модель не включена."}</p>
      </div>
    </section>

    <section className="panel">
      <span className="label">Что проверяли</span>
      <h2>Вопрос модели</h2>
      <p>{r.label_definition}.</p>
      <p className="note">Это отдельное исследование, а не оценка прогноза вашего счёта. Ваш прогноз строится другой,
        сезонной моделью; риск в процентах в нём — модельная оценка, она подписана «оценка».</p>
    </section>

    <section className="panel flat">
      <div className="panel-head"><div><h2>Результаты по этапам</h2>
        <span className="label">Чем больше «пойманных» и меньше «ложных», тем лучше</span></div></div>
      <div className="scroll"><table className="ops"><thead><tr>
        <th>Этап</th><th className="num">Счетов</th><th className="num">Настоящих разрывов</th>
        <th className="num">Поймано</th><th className="num">Ложных тревог</th><th className="num">Доля верных предупреждений</th>
      </tr></thead><tbody>{r.cohorts.map(c => <tr key={c.name}>
        <td><b className="cp">{COHORTS[c.name] ?? c.name}</b></td>
        <td className="num">{c.accounts}</td>
        <td className="num">{c.confusion_matrix.tp + c.confusion_matrix.fn}</td>
        <td className="num">{c.confusion_matrix.tp} · {pct(c.metrics.recall?.value)}</td>
        <td className="num">{c.confusion_matrix.fp}</td>
        <td className="num">{pct(c.metrics.precision?.value)}</td>
      </tr>)}</tbody></table></div>
    </section>

    <div className="grid2 top0">
      <section className="panel dash">
        <span className="label">Почему не в продукте</span>
        {r.release.allowed === false ? <ul className="plain">{(r.release.reasons ?? []).map(x =>
          <li key={x}>{RELEASE[x] ?? x}</li>)}</ul> : <p>Критерии выпуска пройдены.</p>}
        <Leaders rows={[
          ["Горизонт", `${r.horizon_days} дн.`],
          ["Счетов на новых данных", unseen.accounts],
          ["Окон проверки", unseen.windows],
        ]} />
      </section>
      <section className="panel">
        <span className="label">Честные ограничения</span>
        <ul className="plain">{r.limitations.map(x => <li key={x}>{x}</li>)}</ul>
      </section>
    </div>
    <p className="note">Полный отчёт с определениями всех метрик доступен по адресу <span className="mono">/api/v1/models/quality</span>.
      {" "}<Link to="/forecast">← к прогнозу</Link></p>
  </div>;
}
