import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Login } from "./features/auth/Login";
import { AppShell } from "./app/AppShell";
import { ApiError, CashCastApi, type User } from "./shared/api";
import { Aura } from "./ui/Aura";
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
  if (me.data && !expired) {
    return <AppShell key={me.data.id} user={me.data} logout={() => void logout()} logoutError={logoutError} />;
  }
  return <Entry>
    {me.isPending ? <p role="status">Проверяем сессию…</p>
      : me.error && !expired
        ? <div role="alert">API недоступен: {me.error.message} <button onClick={() => void me.refetch()}>Повторить</button></div>
        : <Login onLogin={onLogin} />}
  </Entry>;
}

function Entry({ children }: { children: ReactNode }) {
  return <main className="login">
    <div>
      <div className="brand"><span className="mark" /><b>CashCast</b></div>
      <p className="label">Прогноз денежного потока по выписке счёта</p>
      <div className="statusbox" style={{ minHeight: 120, marginBottom: 18 }}><Aura tone="ok" cell={6} />
        <span className="crop tl" /><span className="crop tr" /><span className="crop bl" /><span className="crop br" /></div>
      {children}
    </div>
  </main>;
}
