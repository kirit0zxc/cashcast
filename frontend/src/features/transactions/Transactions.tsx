import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CashCastApi, money, type Page, type Transaction } from "../../shared/api";
import { CategoryEditor } from "./CategoryEditor";

// Курсор сбрасывается размонтированием при смене компании/счёта или после импорта.
export function Transactions({ api, companyId, accountId }: {
  api: CashCastApi; companyId: string; accountId: string;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["transactions", companyId, accountId, cursor],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ account_id: accountId, limit: "25" });
      if (cursor) params.set("cursor", cursor);
      return api.request<Page<Transaction>>(`/companies/${companyId}/transactions?${params}`, { signal });
    }, enabled: !!accountId,
  });
  return <section className="panel"><h2>Операции</h2>
    {query.isFetching && <p role="status">Загрузка…</p>}
    {query.error && <p role="alert">{query.error.message}</p>}
    {query.data && <>
      {!query.data.items.length && <p>Операций пока нет. Импортируйте выписку.</p>}
      <div className="scroll"><table aria-label="Банковские операции"><thead><tr><th>Дата</th><th>Контрагент / назначение</th>
        <th>Категория</th><th>Приход</th><th>Расход</th></tr></thead><tbody>
        {query.data.items.map(t => <tr key={t.id}><td>{t.booked_on}</td><td>{t.counterparty_name ?? "—"}
          <small>{t.purpose}</small></td><td><CategoryEditor api={api} transaction={t}
            companyId={companyId} accountId={accountId} /></td>
          <td>{t.direction === "in" ? money(t.amount_minor) : "—"}</td>
          <td>{t.direction === "out" ? money(t.amount_minor) : "—"}</td></tr>)}
      </tbody></table></div>
      <button disabled={!cursor || query.isFetching} onClick={() => setCursor(null)}>В начало</button>{" "}
      <button disabled={!query.data.next_cursor || query.isFetching}
        onClick={() => setCursor(query.data.next_cursor)}>Следующие 25</button>
    </>}
  </section>;
}
