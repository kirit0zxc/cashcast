import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CashCastApi, money, type PlanFact } from "../../shared/api";
import { ProposalConfirmation } from "./ProposalConfirmation";
import { useCompanyCanWrite } from "../../shared/company-permissions";

// GET показывает предложения; оплатой становятся только записанные сервером связи.
export function PlanFactPanel({ api, companyId, accountId, revision, onApplied }: {
  api: CashCastApi; companyId: string; accountId: string; revision: number; onApplied: () => void;
}) {
  const canWrite = useCompanyCanWrite();
  const cache = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const path = `/companies/${companyId}/plan-fact?${new URLSearchParams({ account_id: accountId, as_of: today })}`;
  const query = useQuery({ queryKey: ["plan-fact", companyId, accountId, today, revision],
    queryFn: ({ signal }) => api.request<PlanFact>(path, { signal }) });
  const apply = useMutation({ mutationFn: () => api.post<PlanFact>(path), onSuccess: async () => {
    await cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] });
    onApplied();
  } });
  const confirm = useMutation({ mutationFn: (body: {
    planned_event_id: string; transaction_id: string; matched_amount_minor: number;
  }) => api.post<PlanFact>(`/companies/${companyId}/plan-fact/confirm`, { account_id: accountId, ...body }),
  onSuccess: async () => {
    await cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] });
    onApplied();
  }, onError: async () => {
    // Устаревший proposal нельзя оставлять единственным источником для повторной кнопки.
    await cache.invalidateQueries({ queryKey: ["plan-fact", companyId, accountId] });
  } });
  const proposals = query.data?.proposals ?? [];
  const names = new Map(query.data?.items.map(({ event }) =>
    [event.id, event.counterparty_name ?? event.counterparty_ref ?? event.id]));
  const statuses: Record<string, string> = { planned: "Ожидается", partially_paid: "Частично оплачен",
    paid: "Оплачен", cancelled: "Отменён" };
  return <section className="panel"><h2>Сверка плана и факта</h2>
    <p>На {today} UTC. Предложения ещё не являются оплатой; альтернативные связи не суммируются.</p>
    {canWrite && <button disabled={query.isFetching || apply.isPending || confirm.isPending || !proposals.some(p => p.auto_confirm)}
      onClick={() => apply.mutate()}>Применить однозначные совпадения</button>}
    {query.isFetching && <p role="status">Получаем план-факт…</p>}
    {apply.isPending && <p role="status">Проверяем и записываем однозначные оплаты…</p>}
    {apply.isSuccess && <p role="status">Сверка выполнена. Прогноз обновляется автоматически.</p>}
    {confirm.isPending && <p role="status">Подтверждаем выбранную оплату…</p>}
    {confirm.isSuccess && <p role="status">Оплата подтверждена. Новый прогноз учтёт изменившийся остаток.</p>}
    {[query.error, apply.error, confirm.error].filter(Boolean).map((error, index) => <p role="alert" key={index}>{error!.message}</p>)}
    {query.data?.items.length === 0 && <p>На выбранном счёте пока нет известных планов.</p>}
    {!!query.data?.items.length && <div className="scroll"><table aria-label="План и связанные оплаты"><thead><tr>
      <th>Плановая дата</th><th>Документ / контрагент</th><th>Сумма</th><th>Связано с операциями</th><th>Остаток</th><th>Состояние</th>
    </tr></thead><tbody>{query.data.items.map(({ event, confirmed_amount_minor }) => <tr key={event.id}>
      <td>{event.due_date}</td><td>{names.get(event.id)}{event.source_ref && <small>{event.source_ref}</small>}</td>
      <td>{money(event.amount_minor)}</td><td>{money(confirmed_amount_minor)}</td>
      <td>{money(event.remaining_amount_minor)}</td><td>{statuses[event.status] ?? event.status}
        {event.due_date < today && event.remaining_amount_minor > 0 && !["paid", "cancelled"].includes(event.status)
          && <small>Просрочен по плановой дате</small>}</td>
    </tr>)}</tbody></table></div>}
    <details><summary>Предложения и подтверждённые связи</summary>
      <ul>{proposals.map(proposal => <li key={`${proposal.planned_event_id}:${proposal.transaction_id}`}>
        {names.get(proposal.planned_event_id)} → операция {proposal.transaction_id}: {money(proposal.matched_amount_minor)}.
        {proposal.auto_confirm ? " Однозначное совпадение." : " Требуется ручная проверка."}
        <small>{proposal.reason}</small>
        {canWrite && query.data?.items.find(item => item.event.id === proposal.planned_event_id) && <ProposalConfirmation
          key={`${proposal.planned_event_id}:${proposal.transaction_id}:${proposal.matched_amount_minor}`}
          api={api} companyId={companyId} accountId={accountId} proposal={proposal}
          event={query.data.items.find(item => item.event.id === proposal.planned_event_id)!.event}
          disabled={query.isFetching || apply.isPending || confirm.isPending}
          onEdit={() => confirm.reset()} onConfirm={amount => confirm.mutate({
            planned_event_id: proposal.planned_event_id, transaction_id: proposal.transaction_id,
            matched_amount_minor: amount,
          })} />}
      </li>)}</ul>
      <p>Подтверждённых связей: {query.data?.confirmed_matches.length ?? 0}.</p>
      <ul>{query.data?.confirmed_matches.map(link => <li key={`${link.planned_event_id}:${link.transaction_id}`}>
        {names.get(link.planned_event_id)} → операция {link.transaction_id}: {money(link.matched_amount_minor)}.
      </li>)}</ul>
    </details>
  </section>;
}
