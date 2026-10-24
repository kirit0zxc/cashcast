import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CashCastApi, money, type PlanFact } from "../../shared/api";
import { ProposalConfirmation } from "./ProposalConfirmation";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { Leaders, Tabs, dmy } from "../../ui/Blank";
import { PLAN_STATUSES } from "./PlannedEvents";

// GET показывает предложения; оплатой становятся только записанные сервером связи.
export function PlanFactPanel({ api, companyId, accountId, onApplied }: {
  api: CashCastApi; companyId: string; accountId: string; onApplied: () => void;
}) {
  const canWrite = useCompanyCanWrite();
  const [tab, setTab] = useState<"balances" | "proposals" | "confirmed">("balances");
  const cache = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const path = `/companies/${companyId}/plan-fact?${new URLSearchParams({ account_id: accountId, as_of: today })}`;
  const query = useQuery({ queryKey: ["plan-fact", companyId, accountId, today],
    queryFn: ({ signal }) => api.request<PlanFact>(path, { signal }) });
  async function applied(result: PlanFact) {
    // Оплата уже записана. Отображение сверки не должно зависеть от того,
    // смог ли следующий запрос поставить прогноз в очередь.
    await cache.cancelQueries({ queryKey: ["plan-fact", companyId, accountId] });
    cache.setQueryData(["plan-fact", companyId, accountId, today], result);
    await Promise.all([
      cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] }),
      cache.invalidateQueries({ queryKey: ["plan-fact", companyId, accountId] }),
    ]);
    onApplied();
  }
  const apply = useMutation({ mutationFn: () => api.post<PlanFact>(path), onSuccess: applied });
  const confirm = useMutation({ mutationFn: (body: {
    planned_event_id: string; transaction_id: string; matched_amount_minor: number;
  }) => api.post<PlanFact>(`/companies/${companyId}/plan-fact/confirm`, { account_id: accountId, ...body }),
  onSuccess: applied, onError: async () => {
    // Устаревший proposal нельзя оставлять единственным источником для повторной кнопки.
    await cache.invalidateQueries({ queryKey: ["plan-fact", companyId, accountId] });
  } });
  const proposals = query.data?.proposals ?? [];
  const names = new Map(query.data?.items.map(({ event }) =>
    [event.id, event.counterparty_name ?? event.counterparty_ref ?? event.id]));
  const items = query.data?.items ?? [];
  const confirmed = query.data?.confirmed_matches ?? [];
  const busy = query.isFetching || apply.isPending || confirm.isPending;
  return <section className="panel flat">
    <div className="panel-head">
      <div><h2>Сверка плана и факта</h2>
        <span className="label">Срез {dmy(today)} UTC · предложения ещё не являются оплатой; альтернативные связи не суммируются</span></div>
      {canWrite && <button disabled={busy || !proposals.some(p => p.auto_confirm)}
        onClick={() => apply.mutate()}>Применить однозначные совпадения</button>}
    </div>
    <div className="pad">
      <Tabs label="Сверка" value={tab} onChange={setTab} items={[
        ["balances", "Остатки по обязательствам"],
        ["proposals", `Предложения · ${proposals.length}`],
        ["confirmed", `Подтверждённые связи · ${confirmed.length}`],
      ]} />
      {query.isFetching && <p role="status">Получаем план-факт…</p>}
      {apply.isPending && <p role="status">Проверяем и записываем однозначные оплаты…</p>}
      {apply.isSuccess && <p role="status">Сверка выполнена. Прогноз обновляется автоматически.</p>}
      {confirm.isPending && <p role="status">Подтверждаем выбранную оплату…</p>}
      {confirm.isSuccess && <p role="status">Оплата подтверждена. Новый прогноз учтёт изменившийся остаток.</p>}
      {[query.error, apply.error, confirm.error].filter(Boolean).map((error, index) => <p role="alert" key={index}>{error!.message}</p>)}

      {tab === "balances" && <>
        {query.data && !items.length && <div className="empty"><b>Планов для сверки нет</b>
          Добавьте плановые платежи или загрузите обязательства.</div>}
        {items.length > 0 && <div className="scroll"><table className="ops" aria-label="План и связанные оплаты"><thead><tr>
          <th>Плановая дата</th><th>Документ / контрагент</th><th className="num">Сумма</th>
          <th className="num">Связано с операциями</th><th className="num">Остаток</th><th>Состояние</th>
        </tr></thead><tbody>{items.map(({ event, confirmed_amount_minor }) => <tr key={event.id}>
          <td className="mono nowrap">{dmy(event.due_date)}</td>
          <td><b className="cp">{names.get(event.id)}</b>
            <small>{event.direction === "in" ? "Поступление" : "Расход"}{event.source_ref && ` · ${event.source_ref}`}</small></td>
          <td className="num">{money(event.amount_minor)}</td><td className="num">{money(confirmed_amount_minor)}</td>
          <td className="num">{money(event.remaining_amount_minor)}</td>
          <td><span className={`tag status-${event.status}`}>{PLAN_STATUSES[event.status] ?? event.status}</span>
            {event.due_date < today && event.remaining_amount_minor > 0 && !["paid", "cancelled"].includes(event.status)
              && <small className="overdue">Просрочен по плановой дате</small>}</td>
        </tr>)}</tbody></table></div>}
      </>}

      {tab === "proposals" && <>
        {query.data && !proposals.length && <div className="empty"><b>Предложений нет</b>
          Подходящих банковских операций рядом с плановыми датами не найдено.</div>}
        <div className="proposals">{proposals.map(proposal => {
          const event = items.find(item => item.event.id === proposal.planned_event_id)?.event;
          return <article className="panel dash proposal" key={`${proposal.planned_event_id}:${proposal.transaction_id}`}>
            <div className="row between">
              <span className={`tag${proposal.auto_confirm ? " now" : ""}`}>{proposal.auto_confirm ? "однозначно" : "ручная проверка"}</span>
              <span className="label">уверенность {Math.round(proposal.confidence * 100)}%</span>
            </div>
            <h3>{names.get(proposal.planned_event_id)} · {money(proposal.matched_amount_minor)}</h3>
            <Leaders rows={[
              ["План", event ? `${dmy(event.due_date)} · остаток ${money(event.remaining_amount_minor)}` : "—"],
              ["Операция", <span className="mono" key="t">{proposal.transaction_id.slice(0, 8)}…</span>],
            ]} />
            <small>{proposal.reason}</small>
            {canWrite && event && <ProposalConfirmation
              key={`${proposal.planned_event_id}:${proposal.transaction_id}:${proposal.matched_amount_minor}`}
              api={api} companyId={companyId} accountId={accountId} proposal={proposal} event={event}
              disabled={busy} onEdit={() => confirm.reset()} onConfirm={amount => confirm.mutate({
                planned_event_id: proposal.planned_event_id, transaction_id: proposal.transaction_id,
                matched_amount_minor: amount,
              })} />}
          </article>;
        })}</div>
      </>}

      {tab === "confirmed" && <>
        {query.data && !confirmed.length && <div className="empty"><b>Подтверждённых связей пока нет</b>
          Связь появляется после применения однозначных совпадений или ручного подтверждения.</div>}
        {confirmed.length > 0 && <div className="scroll"><table className="ops" aria-label="Подтверждённые связи"><thead><tr>
          <th>Документ / контрагент</th><th>Банковская операция</th><th className="num">Распределено</th>
        </tr></thead><tbody>{confirmed.map(link => <tr key={`${link.planned_event_id}:${link.transaction_id}`}>
          <td><b className="cp">{names.get(link.planned_event_id)}</b></td>
          <td className="mono">{link.transaction_id}</td>
          <td className="num">{money(link.matched_amount_minor)}</td>
        </tr>)}</tbody></table></div>}
      </>}
    </div>
  </section>;
}
