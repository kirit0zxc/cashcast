import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAccount } from "../../app/account-context";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { EvaluationReport } from "./EvaluationReport";
import type { EvaluationJob } from "./types";

export function EvaluationPanel() {
  const { accountId } = useAccount();
  // При переключении счёта форма и выбранный отчёт сбрасываются вместе.
  return <AccountEvaluation key={accountId} />;
}

function AccountEvaluation() {
  const { api, companyId, accountId } = useAccount();
  const canWrite = useCompanyCanWrite();
  const [asOf, setAsOf] = useState("");
  const [horizon, setHorizon] = useState(30), [folds, setFolds] = useState(1);
  const [complete, setComplete] = useState(false), [threshold, setThreshold] = useState(0.5);
  const [id, setId] = useState<string | null>(null), [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const history = useQuery({ queryKey: ["evaluations", companyId, accountId],
    queryFn: () => api.request<EvaluationJob[]>(`/companies/${companyId}/evaluations?account_id=${accountId}`),
    enabled: !!accountId, refetchInterval: 5000,
  });
  const job = useQuery({ queryKey: ["evaluation", companyId, accountId, id],
    queryFn: () => api.request<EvaluationJob>(`/evaluations/${id}`), enabled: !!id,
    refetchInterval: query => ["pending", "running"].includes(query.state.data?.status ?? "pending") ? 1500 : false,
  });
  const busy = submitting || !!id && (!job.data || ["pending", "running"].includes(job.data.status)) && !job.isError;
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setSubmitting(true);
    try {
      const accepted = await api.post<EvaluationJob>(`/companies/${companyId}/evaluations`, {
        account_id: accountId, as_of: asOf, horizon_days: horizon, folds,
        complete_statement: complete, threshold, seed: 42,
      });
      setId(accepted.id);
      await history.refetch();
      // Повтор того же ID тоже перечитывает статус после дедупликации.
      if (accepted.id === id) await job.refetch();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось запустить проверку"); }
    finally { setSubmitting(false); }
  }
  return <>
    <section className="panel"><h2>Проверка на скрытой части истории</h2>
      <p>Сначала импортируйте контрольную выписку. Выберите историческую дату: модель увидит только данные до неё,
        а следующие дни используем как факт. Это отдельная проверка, она не меняет обычные прогнозы.</p>
      <form onSubmit={submit}><div className="row">
        <label>Первая дата среза<input type="date" required value={asOf} disabled={busy || !canWrite} onChange={e => setAsOf(e.target.value)} /></label>
        <label>Горизонт, дней<input type="number" min="1" max="90" required value={horizon} disabled={busy || !canWrite} onChange={e => setHorizon(Number(e.target.value))} /></label>
        <label>Последовательных окон<input type="number" min="1" max="12" required value={folds} disabled={busy || !canWrite} onChange={e => setFolds(Number(e.target.value))} /></label>
        <label>Порог предупреждения<input type="number" min="0" max="1" step="0.01" required value={threshold} disabled={busy || !canWrite} onChange={e => setThreshold(Number(e.target.value))} /></label>
      </div><label><input type="checkbox" checked={complete} disabled={busy || !canWrite} onChange={e => setComplete(e.target.checked)} />
        Подтверждаю: на проверяемом периоде выписка содержит все операции</label>
      <p className="note">Без подтверждения считаем ошибки только по наблюдаемым остаткам.
        Пропуски не считаем нулями. Порог фиксируется до проверки; не подбирайте его по контрольным ответам.</p>
      <button disabled={busy || !accountId || !canWrite}>{busy ? "Расчёт выполняется…" : "Проверить качество"}</button></form>
      {!canWrite && <p>Запуск проверки доступен владельцу компании.</p>}
      {(error || job.error) && <p role="alert">{error || (job.error instanceof Error ? job.error.message : "Ошибка загрузки")}</p>}
      {job.data?.status === "failed" && <p role="alert">Проверка не завершена: {job.data.error_code}. Сохраните код ошибки для диагностики.</p>}
      {id && <p className="note">ID проверки: {id} · {job.data?.status ?? "загрузка"}</p>}
      <details><summary>Последние сохранённые проверки</summary>
        {history.isError && <p role="alert">Не удалось загрузить историю проверок.</p>}
        {!history.isLoading && !history.isError && !history.data?.length && <p>Проверок пока нет.</p>}
        <ul>{history.data?.map(item => <li key={item.id}><button type="button" className="ghost"
          disabled={busy} onClick={() => { setId(item.id); setError(""); }}>{item.id} · {item.status}</button></li>)}</ul>
      </details>
    </section>
    {job.data?.report && <EvaluationReport report={job.data.report} id={job.data.id} />}
  </>;
}
