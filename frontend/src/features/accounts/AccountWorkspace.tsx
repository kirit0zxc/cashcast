import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { StatementImport } from "../imports/StatementImport";
import { Transactions } from "../transactions/Transactions";
import { ForecastPanel } from "../forecast/ForecastPanel";
import { PlannedEvents } from "../planning/PlannedEvents";
import { CashCastApi } from "../../shared/api";

interface Account { id: string; company_id: string; name: string; currency: string }

// Ключ родительского компонента отделяет состояние счетов разных компаний.
export function AccountWorkspace({ api, companyId }: { api: CashCastApi; companyId: string }) {
  const [selected, setSelected] = useState("");
  const accounts = useQuery({ queryKey: ["accounts", companyId],
    queryFn: ({ signal }) => api.request<{ items: Account[] }>(`/companies/${companyId}/accounts`, { signal }) });
  const accountId = selected || accounts.data?.items[0]?.id || "";
  return <>
    <section className="panel"><label>Счёт<select value={accountId} onChange={e => setSelected(e.target.value)}>
      {accounts.data?.items.map(a => <option value={a.id} key={a.id}>{a.name} · {a.currency}</option>)}
    </select></label>
      {accounts.isPending && <p role="status">Получаем счета…</p>}
      {accounts.error && <p role="alert">{accounts.error.message}</p>}
      {accounts.data?.items.length === 0 && <p>У компании нет счетов. Обратитесь к владельцу стенда.</p>}
    </section>
    {accountId && <AccountTools key={accountId} api={api} companyId={companyId} accountId={accountId} />}
  </>;
}

function AccountTools({ api, companyId, accountId }: { api: CashCastApi; companyId: string; accountId: string }) {
  const [lastDate, setLastDate] = useState(new Date().toISOString().slice(0, 10));
  const [version, setVersion] = useState(0);
  return <>
    <StatementImport api={api} companyId={companyId} accountId={accountId}
      onCommit={date => { if (date) setLastDate(date); setVersion(v => v + 1); }} />
    <Transactions key={`transactions:${version}`} api={api} companyId={companyId} accountId={accountId} />
    <ForecastPanel key={`forecast:${version}`} api={api} companyId={companyId} accountId={accountId} initialDate={lastDate} />
    <PlannedEvents api={api} companyId={companyId} accountId={accountId} onChanged={() => {
      setLastDate(new Date().toISOString().slice(0, 10)); setVersion(v => v + 1);
    }} />
  </>;
}
