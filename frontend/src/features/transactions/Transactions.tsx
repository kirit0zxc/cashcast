import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CashCastApi, money, type Page, type Transaction } from "../../shared/api";
import { dmy } from "../../ui/Blank";
import { CATEGORIES, CategoryEditor } from "./CategoryEditor";

const PAGE_SIZE = 25;

interface Filters { date_from: string; date_to: string; direction: "" | "in" | "out"; category: string }
const EMPTY: Filters = { date_from: "", date_to: "", direction: "", category: "" };

// Фильтры применяет сервер ко всему запросу, а не к загруженной странице.
// Курсор непрозрачный: храним стек пройденных курсоров, чтобы вернуться назад.
// Смена фильтра или счёта сбрасывает пагинацию.
export function Transactions({ api, companyId, accountId, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string;
  onChanged: () => void;
}) {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors.at(-1) ?? null;
  const invalidRange = !!filters.date_from && !!filters.date_to && filters.date_from > filters.date_to;
  const query = useQuery({
    queryKey: ["transactions", companyId, accountId, filters, cursor],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ account_id: accountId, limit: String(PAGE_SIZE) });
      for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
      if (cursor) params.set("cursor", cursor);
      return api.request<Page<Transaction>>(`/companies/${companyId}/transactions?${params}`, { signal });
    }, enabled: !!accountId && !invalidRange,
  });
  function change(patch: Partial<Filters>) { setFilters(f => ({ ...f, ...patch })); setCursors([null]); }
  const filtered = Object.values(filters).some(Boolean);

  return <>
    <section className="filters" aria-label="Фильтры операций">
      <label>Дата с<input type="date" value={filters.date_from} onChange={e => change({ date_from: e.target.value })} /></label>
      <label>Дата по<input type="date" value={filters.date_to} onChange={e => change({ date_to: e.target.value })} /></label>
      <label>Направление<select value={filters.direction} onChange={e => change({ direction: e.target.value as Filters["direction"] })}>
        <option value="">Все операции</option><option value="in">Поступления</option><option value="out">Списания</option>
      </select></label>
      <label>Категория<select value={filters.category} onChange={e => change({ category: e.target.value })}>
        <option value="">Все категории</option>
        {Object.entries(CATEGORIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <button type="button" className="ghost" disabled={!filtered} onClick={() => change(EMPTY)}>Сбросить</button>
    </section>
    {invalidRange && <p role="alert">Дата «с» позже даты «по».</p>}

    <section className="panel flat">
      <div className="panel-head">
        <span className="label">Операции счёта · по возрастанию даты · стр. {cursors.length}</span>
        {query.isFetching && <span role="status" className="label">Загрузка…</span>}
      </div>
      {query.error && <p role="alert">{query.error.message}</p>}
      {query.data && !query.data.items.length && <div className="empty"><b>{filtered ? "Под фильтр ничего не попало" : "Операций пока нет"}</b>
        {filtered ? "Измените или сбросьте фильтры." : "Импортируйте выписку в разделе «Импорт данных»."}</div>}
      {query.data && query.data.items.length > 0 && <div className="scroll"><table className="ops" aria-label="Банковские операции">
        <thead><tr><th>Дата</th><th>Контрагент / назначение</th><th>Категория</th>
          <th className="num">Приход</th><th className="num">Расход</th></tr></thead>
        <tbody>{query.data.items.map(t => <tr key={t.id}>
          <td className="mono nowrap">{dmy(t.booked_on)}</td>
          <td><b className="cp">{t.counterparty_name ?? "—"}</b><small>{t.purpose}</small></td>
          <td className="cat"><CategoryEditor api={api} transaction={t}
            companyId={companyId} accountId={accountId} onChanged={onChanged} /></td>
          <td className="num">{t.direction === "in" ? `+${money(t.amount_minor)}` : "—"}</td>
          <td className="num">{t.direction === "out" ? `−${money(t.amount_minor)}` : "—"}</td>
        </tr>)}</tbody>
      </table></div>}
      {query.data && <div className="pager">
        <small>Показано {query.data.items.length} на странице. Сумма страницы не является итогом периода.</small>
        <button type="button" className="ghost" disabled={cursors.length < 2 || query.isFetching}
          onClick={() => setCursors([null])}>В начало</button>
        <button type="button" className="ghost" disabled={cursors.length < 2 || query.isFetching}
          onClick={() => setCursors(c => c.slice(0, -1))}>Назад</button>
        <button type="button" disabled={!query.data.next_cursor || query.isFetching}
          onClick={() => setCursors(c => [...c, query.data!.next_cursor])}>Следующие {PAGE_SIZE}</button>
      </div>}
    </section>
  </>;
}
