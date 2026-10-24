import { useState, type FormEvent } from "react";
import { CashCastApi, type User } from "../../shared/api";

// Пароль существует только в форме и очищается после успешного входа.
export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const user = await new CashCastApi().login(email, password);
      setPassword(""); onLogin(user);
    } catch (error) { setError(error instanceof Error ? error.message : "Не удалось войти"); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="panel narrow"><h2>Вход</h2>
    <label>Email<input type="email" autoComplete="username" required value={email}
      onChange={e => setEmail(e.target.value)} /></label>
    <label>Пароль<input type="password" autoComplete="current-password" required value={password}
      onChange={e => setPassword(e.target.value)} /></label>
    <button disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}
