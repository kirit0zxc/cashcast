import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CashCastApi, money, rublesToMinor, type PlannedEvent } from "../../shared/api";
import { ObligationImport } from "./ObligationImport";

// Форма использует существующий API: будущий платёж становится новым входом прогноза.
export function PlannedEvents({ api, companyId, accountId, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string; onChanged: () => void;
}) {
  const client = useQueryClient();
  const key = ["planned-events", companyId, accountId];
  const [amount, setAmount] = useState("");
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [due, setDue] = useState(new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10));
  const [counterparty, setCounterparty] = useState("");
  const events = useQuery({ queryKey: key, queryFn: ({ signal }) =>
    api.request<PlannedEvent[]>(`/companies/${companyId}/planned-events`, { signal }) });
  async function changed() { await client.invalidateQueries({ queryKey: key }); onChanged(); }
  const create = useMutation({ mutationFn: () => api.post<PlannedEvent>(`/companies/${companyId}/planned-events`, {
    account_id: accountId, amount_minor: rublesToMinor(amount), direction, due_date: due,
    kind: "manual", counterparty_name: counterparty.trim() || null,
  }), onSuccess: async () => { setAmount(""); await changed(); } });
  const cancel = useMutation({ mutationFn: (id: string) => api.patch<PlannedEvent>(`/planned-events/${id}`, {
    status: "cancelled",
  }), onSuccess: changed });
  function submit(event: FormEvent) { event.preventDefault(); create.mutate(); }
  const rows = events.data?.filter(e => e.account_id === accountId) ?? [];
  const statuses: Record<string, string> = { planned: "Ожидается", partially_paid: "Частично оплачен",
    paid: "Оплачен", cancelled: "Отменён" };
  return <section className="panel"><h2>Будущие платежи и обязательства</h2>
    <form className="row" onSubmit={submit}>
      <label>Движение по плану<select disabled={create.isPending} value={direction}
        onChange={e => setDirection(e.target.value as "in" | "out")}>
        <option value="out">Расход</option><option value="in">Поступление</option></select></label>
      <label>Планируемая сумма, ₽<input required inputMode="decimal" disabled={create.isPending}
        value={amount} onChange={e => { setAmount(e.target.value); create.reset(); }} /></label>
      <label>Плановая дата<input required type="date" disabled={create.isPending}
        value={due} onChange={e => { setDue(e.target.value); create.reset(); }} /></label>
      <label>Контрагент по плану<input maxLength={500} disabled={create.isPending} value={counterparty}
        onChange={e => { setCounterparty(e.target.value); create.reset(); }} /></label>
      <button disabled={create.isPending}>Добавить платёж</button>
    </form>
    {create.isSuccess && <p role="status">План сохранён. Дата среза переключена на сегодня; рассчитайте прогноз.</p>}
    <ObligationImport api={api} companyId={companyId} accountId={accountId} onChanged={changed} />
    {events.isPending && <p role="status">Получаем планы…</p>}
    {[events.error, create.error, cancel.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
    {events.data && rows.length === 0 && <p>На выбранном счёте пока нет плановых платежей.</p>}
    {rows.length > 0 && <div className="scroll"><table aria-label="Плановые платежи"><thead><tr>
      <th>Дата</th><th>Контрагент</th><th>Движение</th><th>Сумма / остаток</th><th>Источник</th><th>Статус</th><th>Действие</th>
    </tr></thead><tbody>{rows.map(e => <tr key={e.id} data-testid={`planned-event-${e.id}`}>
      <td>{e.due_date}</td><td>{e.counterparty_name ?? e.counterparty_ref ?? "—"}</td>
      <td>{e.direction === "in" ? "Поступление" : "Расход"}</td>
      <td>{money(e.amount_minor)} / {money(e.remaining_amount_minor)}</td>
      <td>{e.source === "manual" ? "Ручной ввод" : e.source === "csv" ? "CSV" : e.source}
        {e.provenance && <small>{e.provenance}</small>}{e.source_ref && <small>{e.source_ref}</small>}
        {e.tax_regime && <small>Налоговый режим из документа: {e.tax_regime}</small>}</td>
      <td>{statuses[e.status] ?? e.status}</td>
      <td><button disabled={cancel.isPending || ["cancelled", "paid"].includes(e.status)}
        onClick={() => cancel.mutate(e.id)}>Отменить</button></td>
    </tr>)}</tbody></table></div>}
  </section>;
}
