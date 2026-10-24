import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { CashCastApi } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { ChatCardView } from "./ChatCards";
import type { ChatEntry, ChatReply } from "./types";

// Переключение счёта размонтирует чат: чужая история не переносится в новый контекст.
export function AssistantPanel({ api, companyId, accountId, asOf, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string; asOf: string; onChanged: () => void;
}) {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("statement");
  const [mapping, setMapping] = useState("");
  const active = useRef(false);
  const retry = useRef<{ request_id: string; messages: { role: string; content: string }[]; text: string; asOf: string } | null>(null);
  const cache = useQueryClient();
  const canWrite = useCompanyCanWrite();
  const status = useQuery({ queryKey: ["assistant-status"], retry: false,
    queryFn: () => api.request<{ enabled: boolean; model: string }>("/assistant/status") });
  function addReply(reply: ChatReply, changed = false) {
    setEntries(old => [...old, { id: crypto.randomUUID(), role: "assistant", content: reply.text, cards: reply.cards }]);
    if (changed) { void cache.invalidateQueries(); onChanged(); }
  }
  async function send(text: string) {
    if (active.current || !text.trim()) return;
    active.current = true; setBusy(true); setError("");
    if (!retry.current || retry.current.text !== text) {
      const history = entries.slice(-10).map(entry => ({ role: entry.role, content: (entry.content +
        (entry.cards.length ? "\nКарточки: " + entry.cards.map(c => JSON.stringify({ title: c.title,
          forecast_id: c.kind === "forecast" ? c.data.id : c.data.forecast_run_id ?? c.data.forecast_id,
          next_cursor: c.data.next_cursor })).join("; ") : "")).slice(0, 6000) }));
      retry.current = { request_id: crypto.randomUUID(), text, asOf,
        messages: [...history, { role: "user", content: text }] };
      setEntries(old => [...old, { id: crypto.randomUUID(), role: "user", content: text, cards: [] }]);
    }
    try {
      const reply = await api.post<ChatReply>(`/companies/${companyId}/assistant/chat`, {
        request_id: retry.current.request_id, account_id: accountId, as_of: retry.current.asOf, messages: retry.current.messages,
      });
      retry.current = null; addReply(reply); setInput("");
      if (reply.error_code) setError(reply.text);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось отправить сообщение"); }
    finally { active.current = false; setBusy(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void send(input); }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file || active.current) return;
    active.current = true; setBusy(true); setError("");
    const form = new FormData(); form.set("file", file); form.set("import_kind", kind); form.set("as_of", asOf);
    if (mapping.trim() && kind === "statement") form.set("mapping", mapping);
    try {
      addReply(await api.request<ChatReply>(`/companies/${companyId}/accounts/${accountId}/assistant/uploads`,
        { method: "POST", body: form }));
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось проверить CSV"); }
    finally { active.current = false; setBusy(false); }
  }
  return <section className="panel assistant" aria-label="ИИ-ассистент CashCast">
    <h2>Ассистент CashCast</h2>
    <p>Объясняет данные выбранного счёта, показывает графики и предлагает действия.
      Все изменения — только после кнопки «Подтвердить действие».</p>
    <p><small>Сообщения и необходимые финансовые показатели передаются DeepSeek через OpenRouter.
      Реквизиты и исходные назначения из базы скрываются. Не вводите пароли и ключи.</small></p>
    {status.data && <p>Модель: {status.data.model}. {!status.data.enabled && "Ключ на сервере пока не настроен."}</p>}
    {status.error && <p role="alert">{status.error.message}</p>}
    <div className="row">
      {["Покажи последний прогноз и объясни риски", "Покажи суммы расходов по категориям",
        "Какие действия помогут избежать кассового разрыва?"].map(text => <button type="button" key={text}
          disabled={busy || !status.data?.enabled} onClick={() => void send(text)}>{text}</button>)}
    </div>
    <div className="assistant-messages" aria-live="polite">
      {entries.map(entry => <article key={entry.id} className={`assistant-message ${entry.role}`}>
        <strong>{entry.role === "user" ? "Вы" : "CashCast"}</strong><p className="assistant-text">{entry.content}</p>
        {entry.cards.map((card, i) => <ChatCardView key={String(card.data.action_id ?? i)} card={card} api={api}
          companyId={companyId} accountId={accountId} onReply={addReply} />)}
      </article>)}
    </div>
    <form onSubmit={submit}><label>Сообщение ассистенту<textarea value={input} maxLength={6000} rows={3}
      disabled={busy} onChange={e => setInput(e.target.value)} placeholder="Что будет, если клиент задержит оплату?" /></label>
      <button disabled={busy || !input.trim() || !status.data?.enabled}>Отправить ассистенту</button>
      <button type="button" disabled={busy} onClick={() => { setEntries([]); retry.current = null; }}>Очистить чат</button>
    </form>
    {canWrite && <details><summary>Прикрепить CSV в чат</summary><form onSubmit={upload}>
      <label>Тип CSV<select value={kind} disabled={busy} onChange={e => setKind(e.target.value)}>
        <option value="statement">Банковская выписка</option><option value="obligations">Обязательства</option>
      </select></label><label>Файл для ассистента<input type="file" accept=".csv,text/csv" disabled={busy}
        onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      <p>Для выписки используется формат организаторов: ; и UTF-8 BOM. Файл остаётся на сервере CashCast.</p>
      {kind === "statement" && <details><summary>Другое соответствие колонок</summary>
        <label>JSON колонок для чата<textarea value={mapping} disabled={busy} onChange={e => setMapping(e.target.value)} /></label>
      </details>}
      <button disabled={busy || !file}>Проверить CSV в чате</button>
    </form></details>}
    {busy && <p role="status">Ассистент получает данные…</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
