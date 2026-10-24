import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Login } from "./features/auth/Login";
import { AccountWorkspace } from "./features/accounts/AccountWorkspace";
import { ApiError, CashCastApi, type User } from "./shared/api";
import { CompanyPermission } from "./shared/company-permissions";
import "./app.css";

// Смена пользователя полностью очищает кэш данных предыдущей сессии.
export function App() {
  const queryClient = useQueryClient();
  const [logoutError, setLogoutError] = useState("");
  const me = useQuery({ queryKey: ["me"], queryFn: () => new CashCastApi().me(), retry: false });
  function onLogin(user: User) {
    queryClient.removeQueries({ predicate: q => q.queryKey[0] !== "me" });
    queryClient.setQueryData(["me"], user);
  }
  async function logout() {
    if (!me.data) return;
    setLogoutError("");
    try { await new CashCastApi(me.data.csrf_token).logout(); }
    catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        setLogoutError(error instanceof Error ? error.message : "Не удалось завершить сессию");
        return;
      }
    }
    queryClient.removeQueries({ predicate: q => q.queryKey[0] !== "me" });
    queryClient.setQueryData(["me"], null);
  }
  const expired = me.error instanceof ApiError && me.error.status === 401;
  return <main><header><h1>CashCast</h1><p>Прогноз денежного потока по выписке счёта</p>
    {me.data && !expired && <button onClick={() => void logout()}>Выйти ({me.data.email})</button>}</header>
    {logoutError && <p role="alert">{logoutError}</p>}
    {me.isPending ? <p role="status">Проверяем сессию…</p> : expired ? <Login onLogin={onLogin} /> : me.data
      ? <Workspace key={me.data.id} user={me.data} />
      : me.error && !(me.error instanceof ApiError && me.error.status === 401)
        ? <div role="alert">API недоступен: {me.error.message} <button onClick={() => void me.refetch()}>Повторить</button></div>
        : <Login onLogin={onLogin} />}
  </main>;
}

function Workspace({ user }: { user: User }) {
  const [companyId, setCompanyId] = useState(user.companies[0]?.id ?? "");
  const api = useMemo(() => new CashCastApi(user.csrf_token), [user.csrf_token]);
  const role = user.companies.find(company => company.id === companyId)?.role;
  return <>
    <section className="panel row">
      <label>Компания<select value={companyId} onChange={e => setCompanyId(e.target.value)}>
        {user.companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select></label>
    </section>
    {!companyId && <p>Нет доступных компаний. Обратитесь к владельцу стенда.</p>}
    {companyId && <CompanyPermission key={companyId} role={role}>
      {role !== "owner" && <p role="status">Только чтение: можно просматривать данные и сохранённые расчёты.</p>}
      <AccountWorkspace api={api} companyId={companyId} />
    </CompanyPermission>}
  </>;
}
