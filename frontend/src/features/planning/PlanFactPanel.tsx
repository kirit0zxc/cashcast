import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CashCastApi, money, type PlannedEvent } from "../../shared/api";

interface PlanFact {
  account_id: string; as_of: string;
  items: { event: PlannedEvent; confirmed_amount_minor: number }[];
  confirmed_matches: { planned_event_id: string; transaction_id: string; matched_amount_minor: number }[];
  proposals: { planned_event_id: string; transaction_id: string; matched_amount_minor: number;
    confidence: number; reason: string; auto_confirm: boolean }[];
}

// GET показывает предложения; оплатой становятся только записанные сервером связи.
export function PlanFactPanel({ api, companyId, accountId, revision, onApplied }: {
  api: CashCastApi; companyId: string; accountId: string; revision: number; onApplied: () => void;
}) {
  const cache = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const path = `/companies/${companyId}/plan-fact?${new URLSearchParams({ account_id: accountId, as_of: today })}`;
  const query = useQuery({ queryKey: ["plan-fact", companyId, accountId, today, revision],
    queryFn: ({ signal }) => api.request<PlanFact>(path, { signal }) });
  const apply = useMutation({ mutationFn: () => api.post<PlanFact>(path), onSuccess: async () => {
    await cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] });
    onApplied();
  } });
  const proposals = query.data?.proposals ?? [];
  const names = new Map(query.data?.items.map(({ event }) =>
    [event.id, event.counterparty_name ?? event.counterparty_ref ?? event.id]));
  const statuses: Record<string, string> = { planned: "Ожидается", partially_paid: "Частично оплачен",
    paid: "Оплачен", cancelled: "Отменён" };
  return <section className="panel"><h2>Сверка плана и факта</h2>
    <p>На {today} UTC. Предложения ещё не являются оплатой; альтернативные связи не суммируются.</p>
    <button disabled={query.isFetching || apply.isPending || !proposals.some(p => p.auto_confirm)}
      onClick={() => apply.mutate()}>Применить однозначные совпадения</button>
    {query.isFetching && <p role="status">Получаем план-факт…</p>}
    {apply.isPending && <p role="status">Проверяем и записываем однозначные оплаты…</p>}
    {apply.isSuccess && <p role="status">Сверка выполнена. Для нового прогноза нажмите «Рассчитать».</p>}
    {[query.error, apply.error].filter(Boolean).map((error, index) => <p role="alert" key={index}>{error!.message}</p>)}
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
        {proposal.auto_confirm ? " Однозначное совпадение." : " Требуется ручная проверка; подтверждение пока недоступно."}
        <small>{proposal.reason}</small>
      </li>)}</ul>
      <p>Подтверждённых связей: {query.data?.confirmed_matches.length ?? 0}.</p>
      <ul>{query.data?.confirmed_matches.map(link => <li key={`${link.planned_event_id}:${link.transaction_id}`}>
        {names.get(link.planned_event_id)} → операция {link.transaction_id}: {money(link.matched_amount_minor)}.
      </li>)}</ul>
    </details>
  </section>;
}
