import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { CashCastApi, type User } from "../shared/api";
import { CompanyPermission, useCompanyCanWrite } from "../shared/company-permissions";
import { Aura } from "../ui/Aura";
import { AccountProvider } from "./account-context";
import { Empty } from "../ui/Empty";
import { ASSISTANT_ROUTE, Link, ROUTES, normalizeLocation, useRoute, type RoutePath } from "./router";
import { Pages } from "../pages/Pages";

interface Account { id: string; company_id: string; name: string; currency: string }

// App → AppShell → CompanyPermission → AccountProvider → страницы.
// Компания и счёт общие для всех разделов; смена любого из них сбрасывает контекст счёта.
export function AppShell({ user, logout, logoutError }: {
  user: User; logout: () => void; logoutError: string;
}) {
  const route = useRoute();
  useEffect(normalizeLocation, []);
  const api = useMemo(() => new CashCastApi(user.csrf_token), [user.csrf_token]);
  const [companyId, setCompanyId] = useState(user.companies[0]?.id ?? "");
  const [selectedAccount, setSelectedAccount] = useState("");
  const role = user.companies.find(company => company.id === companyId)?.role;
  const accounts = useQuery({
    queryKey: ["accounts", companyId], enabled: !!companyId,
    queryFn: ({ signal }) => api.request<{ items: Account[] }>(`/companies/${companyId}/accounts`, { signal }),
  });
  const accountId = accounts.data?.items.some(a => a.id === selectedAccount)
    ? selectedAccount : accounts.data?.items[0]?.id ?? "";

  return <div className="app">
    <div className="topline">
      <span className="logo">cashcast.</span>
      <div className="context">
        <label>Компания<select value={companyId} onChange={e => { setCompanyId(e.target.value); setSelectedAccount(""); }}>
          {user.companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></label>
        {companyId && <label>Счёт<select value={accountId} disabled={!accounts.data?.items.length}
          onChange={e => setSelectedAccount(e.target.value)}>
          {accounts.data?.items.map(a => <option value={a.id} key={a.id}>{a.name} · {a.currency}</option>)}
        </select></label>}
        {role && role !== "owner" && <span className="chip">только чтение</span>}
      </div>
    </div>
    <div className="shell">
      <Sidebar route={route} user={user} logout={logout} logoutError={logoutError} />
      <main>
        {!companyId && <Empty title="Нет доступных компаний" text="Обратитесь к владельцу стенда." />}
        {accounts.isPending && companyId && <p role="status">Получаем счета…</p>}
        {accounts.error && <p role="alert">{accounts.error.message}</p>}
        {accounts.data?.items.length === 0 && <Empty title="У компании нет счетов" text="Обратитесь к владельцу стенда." />}
        {companyId && accountId && <CompanyPermission key={`${companyId}:${accountId}`} role={role}>
          <AccountProvider api={api} companyId={companyId} accountId={accountId}>
            <ReadOnlyNote />
            <Pages route={route} />
          </AccountProvider>
        </CompanyPermission>}
        <div className="foot"><span>cashcast · данные из API</span><span>/// {new Date().getFullYear()}</span><span className="barcode" /></div>
      </main>
    </div>
  </div>;
}

function ReadOnlyNote() {
  const canWrite = useCompanyCanWrite();
  return canWrite ? null : <p role="status">Только чтение: можно просматривать данные и сохранённые расчёты.</p>;
}

function Sidebar({ route, user, logout, logoutError }: {
  route: RoutePath; user: User; logout: () => void; logoutError: string;
}) {
  return <aside className="side">
    <nav className="nav" aria-label="Разделы">
      {ROUTES.map((r, i) => <Link key={r.path} to={r.path} aria-current={route === r.path ? "page" : undefined}>
        <span className="n">0{i + 1}</span>{r.title}
      </Link>)}
    </nav>
    <div className="spacer" />
    <Link className="assist" to={ASSISTANT_ROUTE.path} aria-current={route === ASSISTANT_ROUTE.path ? "page" : undefined}>
      <Aura tone="assistant" cell={4} />
      <span><span className="label">09 · ИИ-ассистент</span><b>Юми</b><small>Вопросы о деньгах счёта</small></span>
    </Link>
    <div className="user">
      <span className="mono">{user.email}</span>
      <button type="button" className="ghost" onClick={logout}>Выйти ({user.email})</button>
    </div>
    {logoutError && <p role="alert">{logoutError}</p>}
  </aside>;
}
