import { useQuery } from "@tanstack/react-query";
import { useAccount } from "../app/account-context";
import { navigate } from "../app/router";
import type { Page, PlannedEvent, Transaction } from "../shared/api";
import { useCompanyCanWrite } from "../shared/company-permissions";

// Первые шаги для счёта без прогноза. Только чтение: есть ли операции и планы.
// Сам расчёт запускает пользователь кнопкой — переход на обзор ничего не ставит в очередь.
export function FirstSteps() {
  const { api, companyId, accountId, forecast: c } = useAccount();
  const canWrite = useCompanyCanWrite();
  const ops = useQuery({ queryKey: ["transactions", companyId, accountId, "first-steps"],
    queryFn: ({ signal }) => api.request<Page<Transaction>>(
      `/companies/${companyId}/transactions?${new URLSearchParams({ account_id: accountId, limit: "1" })}`, { signal }) });
  const plans = useQuery({ queryKey: ["planned-events", companyId, accountId],
    queryFn: ({ signal }) => api.request<PlannedEvent[]>(`/companies/${companyId}/planned-events`, { signal }) });
  const hasOps = !!ops.data?.items.length;
  const hasPlans = !!plans.data?.some(e => e.account_id === accountId);
  const steps = [
    { done: hasOps, title: "Загрузите выписку из банка", text: "CSV за последние месяцы — чем длиннее история, тем точнее прогноз.",
      action: canWrite ? <button type="button" className={hasOps ? "ghost" : ""} onClick={() => navigate("/import")}>Загрузить выписку</button> : null },
    { done: hasPlans, title: "Добавьте будущие платежи", text: "Аренда, налоги, счета поставщиков — то, что вы уже знаете наперёд. Необязательно.",
      action: <button type="button" className="ghost" onClick={() => navigate("/payments")}>Плановые платежи</button> },
    { done: false, title: "Посмотрите прогноз", text: "Мы покажем, хватит ли денег на 30 дней и что делать, если нет.",
      action: canWrite ? <button type="button" disabled={!hasOps || c.working} onClick={c.run}>Построить прогноз</button> : null },
  ];
  return <section className="first-steps" aria-label="Первые шаги">
    <span className="label">С чего начать</span>
    <ol>{steps.map((s, i) => <li key={s.title} className={s.done ? "is-done" : ""}>
      <span className="n mono">{s.done ? "✓" : String(i + 1).padStart(2, "0")}</span>
      <div><b>{s.title}</b><small>{s.text}</small></div>
      {s.action}
    </li>)}</ol>
  </section>;
}
