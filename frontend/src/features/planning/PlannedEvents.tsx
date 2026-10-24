import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent } from "react";
import { CashCastApi, minorToInput, money, rublesToMinor, type PlannedEvent } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { dmy } from "../../ui/Blank";

export const PLAN_STATUSES: Record<string, string> = { planned: "Ожидается", partially_paid: "Частично оплачен",
  paid: "Оплачен", cancelled: "Отменён" };
const SOURCES: Record<string, string> = { manual: "Ручной ввод", csv: "CSV" };
const open = (e: PlannedEvent) => e.status === "planned" || e.status === "partially_paid";

// Форма использует существующий API: будущий платёж становится новым входом прогноза.
// Редактирование — PATCH суммы и даты; закрытый план (оплачен/отменён) не меняется.
export function PlannedEvents({ api, companyId, accountId, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string; onChanged: () => void;
}) {
  const canWrite = useCompanyCanWrite();
  const client = useQueryClient();
  const key = ["planned-events", companyId, accountId];
  const [amount, setAmount] = useState("");
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [due, setDue] = useState(new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10));
  const [counterparty, setCounterparty] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(true);
  const events = useQuery({ queryKey: key, queryFn: ({ signal }) =>
    api.request<PlannedEvent[]>(`/companies/${companyId}/planned-events`, { signal }) });
  async function changed() { await client.invalidateQueries({ queryKey: key }); onChanged(); }
  const create = useMutation({ mutationFn: () => api.post<PlannedEvent>(`/companies/${companyId}/planned-events`, {
    account_id: accountId, amount_minor: rublesToMinor(amount), direction, due_date: due,
    kind: "manual", counterparty_name: counterparty.trim() || null,
  }), onSuccess: async () => { setAmount(""); await changed(); } });
  const cancel = useMutation({ mutationFn: (id: string) => api.patch<PlannedEvent>(`/planned-events/${id}`, {
    status: "cancelled",
  }), onSuccess: async () => { setEditing(null); await changed(); } });
  function submit(event: FormEvent) { event.preventDefault(); if (canWrite) create.mutate(); }
  const all = events.data?.filter(e => e.account_id === accountId) ?? [];
  const rows = showClosed ? all : all.filter(open);
  const today = new Date().toISOString().slice(0, 10);

  return <>
    {canWrite && <section className="panel dash"><span className="label">Новый плановый платёж</span>
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
      {create.isSuccess && <p role="status">План сохранён. Дата среза переключена на сегодня; прогноз обновляется автоматически.</p>}
      {create.error && <p role="alert">{create.error.message}</p>}
    </section>}

    <section className="panel flat">
      <div className="panel-head">
        <div><h2>Будущие платежи и обязательства</h2>
          <span className="label">Показано {rows.length} из {all.length}</span></div>
        <label className="check-inline"><input type="checkbox" checked={showClosed}
          onChange={e => setShowClosed(e.target.checked)} />показывать оплаченные и отменённые</label>
      </div>
      {events.isPending && <p role="status">Получаем планы…</p>}
      {[events.error, cancel.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e!.message}</p>)}
      {events.data && rows.length === 0 && <div className="empty"><b>{all.length ? "Открытых планов нет" : "Плановых платежей нет"}</b>
        {all.length ? "Включите показ закрытых, чтобы увидеть историю." : "Добавьте платёж вручную или загрузите обязательства в разделе «Импорт данных»."}</div>}
      {rows.length > 0 && <div className="scroll"><table className="ops" aria-label="Плановые платежи"><thead><tr>
        <th>Дата</th><th>Обязательство</th><th>Движение</th><th className="num">Сумма</th><th className="num">Осталось</th>
        <th>Статус</th><th>Действие</th>
      </tr></thead><tbody>{rows.map(e => <Fragment key={e.id}>
        <tr data-testid={`planned-event-${e.id}`} className={open(e) ? "" : "closed"}>
          <td className="mono nowrap">{dmy(e.due_date)}</td>
          <td><b className="cp">{e.counterparty_name ?? e.counterparty_ref ?? "—"}</b>
            <small>{SOURCES[e.source] ?? e.source}{e.source_ref && ` · ${e.source_ref}`}</small>
            {e.provenance && <small>{e.provenance}</small>}
            {e.tax_regime && <small>Налоговый режим из документа: {e.tax_regime}</small>}</td>
          <td>{e.direction === "in" ? "Поступление" : "Расход"}</td>
          <td className="num">{money(e.amount_minor)}</td>
          <td className="num">{money(e.remaining_amount_minor)}</td>
          <td><span className={`tag status-${e.status}`}>{PLAN_STATUSES[e.status] ?? e.status}</span>
            {open(e) && e.due_date < today && <small className="overdue">просрочен</small>}</td>
          <td className="actions">{canWrite && <>
            <button type="button" className="ghost" disabled={!open(e) || cancel.isPending}
              aria-expanded={editing === e.id} onClick={() => setEditing(id => id === e.id ? null : e.id)}>Изменить</button>
            <button type="button" className="ghost" disabled={cancel.isPending || !open(e)}
              onClick={() => cancel.mutate(e.id)}>Отменить</button>
          </>}</td>
        </tr>
        {editing === e.id && canWrite && <tr className="editing"><td colSpan={7}>
          <PlanEditor api={api} event={e} onDone={async () => { setEditing(null); await changed(); }}
            onClose={() => setEditing(null)} />
        </td></tr>}
      </Fragment>)}</tbody></table></div>}
      <div className="pager"><small>Оплату проверяем по банковским операциям. Подтверждение и частичное распределение —
        в разделе «Сверка оплат». Отменённый план нельзя возобновить.</small></div>
    </section>
  </>;
}

// Меняются только поля, которые отличаются от сохранённых. Сумму нельзя сделать
// меньше уже оплаченной части — это проверит и сервер (422 amount_below_paid).
function PlanEditor({ api, event, onDone, onClose }: {
  api: CashCastApi; event: PlannedEvent; onDone: () => Promise<void>; onClose: () => void;
}) {
  const [amount, setAmount] = useState(minorToInput(event.amount_minor));
  const [due, setDue] = useState(event.due_date);
  const [error, setError] = useState("");
  const paid = event.amount_minor - event.remaining_amount_minor;
  const save = useMutation({
    mutationFn: (body: { amount_minor?: number; due_date?: string }) =>
      api.patch<PlannedEvent>(`/planned-events/${event.id}`, body),
    onSuccess: onDone,
  });
  function submit(e: FormEvent) {
    e.preventDefault(); setError("");
    try {
      const minor = rublesToMinor(amount);
      if (minor < paid) throw new Error(`Сумма не может быть меньше уже оплаченной части: ${money(paid)}`);
      const body: { amount_minor?: number; due_date?: string } = {};
      if (minor !== event.amount_minor) body.amount_minor = minor;
      if (due !== event.due_date) body.due_date = due;
      if (!Object.keys(body).length) { onClose(); return; }
      save.mutate(body);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Проверьте сумму"); }
  }
  return <form className="row editor" onSubmit={submit} aria-label="Изменение планового платежа">
    <label>Новая сумма, ₽<input required inputMode="decimal" disabled={save.isPending} value={amount}
      onChange={e => { setAmount(e.target.value); setError(""); save.reset(); }} /></label>
    <label>Новая дата<input required type="date" disabled={save.isPending} value={due}
      onChange={e => { setDue(e.target.value); save.reset(); }} /></label>
    <button disabled={save.isPending}>Сохранить изменения</button>
    <button type="button" className="ghost" disabled={save.isPending} onClick={onClose}>Закрыть</button>
    <small>{paid > 0 ? `Уже оплачено ${money(paid)}; остаток пересчитается от новой суммы.` : "Оплат по плану ещё нет."}
      {" "}После сохранения прогноз обновится автоматически.</small>
    {(error || save.error) && <p role="alert">{error || save.error!.message}</p>}
  </form>;
}
