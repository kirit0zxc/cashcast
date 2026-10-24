import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CashCastApi, money, rublesToMinor, type MatchProposal, type Page,
  type PlannedEvent, type Transaction } from "../../shared/api";

// Перед денежным действием показываем реальные реквизиты операции через существующий GET.
export function ProposalConfirmation({ api, companyId, accountId, event, proposal, disabled, onConfirm, onEdit }: {
  api: CashCastApi; companyId: string; accountId: string; event: PlannedEvent;
  proposal: MatchProposal; disabled: boolean; onConfirm: (amount: number) => void; onEdit: () => void;
}) {
  const [opened, setOpened] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const minor = BigInt(proposal.matched_amount_minor);
  const [amount, setAmount] = useState(`${minor / 100n}.${(minor % 100n).toString().padStart(2, "0")}`);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["proposal-operation", companyId, accountId, event.id, proposal.transaction_id, cursor],
    queryFn: ({ signal }) => {
      // Matcher допускает только +/-7дней от срока; будущие факты не подходят.
      const start = new Date(`${event.due_date}T00:00:00Z`);
      start.setUTCDate(start.getUTCDate() - 7);
      const dateFrom = start.getUTCFullYear() < 1 ? "0001-01-01" : start.toISOString().slice(0, 10);
      const end = new Date(`${event.due_date}T00:00:00Z`);
      end.setUTCDate(end.getUTCDate() + 7);
      const today = new Date().toISOString().slice(0, 10);
      const dateTo = end.getUTCFullYear() > 9999 ? today : [today, end.toISOString().slice(0, 10)].sort()[0];
      const params = new URLSearchParams({ account_id: accountId, date_from: dateFrom,
        date_to: dateTo, direction: event.direction, limit: "200" });
      if (cursor) params.set("cursor", cursor);
      return api.request<Page<Transaction>>(`/companies/${companyId}/transactions?${params}`, { signal });
    }, enabled: opened,
  });
  const transaction = query.data?.items.find(item => item.id === proposal.transaction_id);
  function submit(e: FormEvent) {
    e.preventDefault(); setError("");
    try {
      const value = rublesToMinor(amount);
      if (value > proposal.matched_amount_minor) throw new Error("Сумма больше предложенного остатка");
      onConfirm(value);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Проверьте сумму"); }
  }
  return <div data-testid={`proposal-${event.id}-${proposal.transaction_id}`}>
    {/* Чтение реквизитов не меняет оплату. Refetch не должен отключать кнопку между
        pointerdown и pointerup и терять клик; денежная форма ниже остаётся заблокированной. */}
    <button type="button" onClick={() => setOpened(value => !value)}>Проверить предложение</button>
    {opened && <>
      {query.isFetching && <p role="status">Загружаем банковскую операцию…</p>}
      {query.error && <p role="alert">{query.error.message}</p>}
      {transaction ? <>
        <p>Операция {transaction.id}: {transaction.booked_on}, {transaction.direction === "in" ? "приход" : "расход"},
          {money(transaction.amount_minor)}. {transaction.counterparty_name ?? "Контрагент не указан"}.</p>
        <p>Назначение: {transaction.purpose ?? "не указано"}.</p>
        <p>План: {event.due_date}, остаток {money(event.remaining_amount_minor)}.</p>
        <form className="row" onSubmit={submit}>
          <label>Подтверждаемая сумма, ₽<input disabled={disabled} required inputMode="decimal" value={amount}
            onChange={e => { setAmount(e.target.value); setError(""); onEdit(); }} /></label>
          <button disabled={disabled || query.isFetching}>Подтвердить выбранную оплату</button>
        </form>
        <p>Действие уменьшит остаток плана. Перед подтверждением сверьте документ и операцию.</p>
      </> : query.data && <>
        <p>Операция не найдена на этой странице. Ничего не подтверждено.</p>
        {query.data.next_cursor && <button type="button" disabled={query.isFetching || disabled}
          onClick={() => setCursor(query.data!.next_cursor)}>Следующая страница поиска операции</button>}
      </>}
      {error && <p role="alert">{error}</p>}
    </>}
  </div>;
}
