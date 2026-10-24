import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAccount } from "../../app/account-context";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { useYumiMood } from "./YumiAvatar";
import { ChatCardView } from "./ChatCards";
import { MarkdownMessage } from "./MarkdownMessage";

const PROMPTS = ["Покажи последний прогноз и объясни риски", "Покажи суммы расходов по категориям",
  "Какие действия помогут избежать кассового разрыва?"];

// Вкладка 09. Открытие делает только чтение /assistant/status; история — в AccountProvider.
export function AssistantPanel() {
  const { api, companyId, accountId, forecast, assistant: chat } = useAccount();
  const canWrite = useCompanyCanWrite();
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("statement");
  const [mapping, setMapping] = useState("");
  const status = useQuery({ queryKey: ["assistant-status"], retry: false,
    queryFn: ({ signal }) => api.request<{ enabled: boolean }>("/assistant/status", { signal }) });
  const enabled = !!status.data?.enabled;
  // Новое сообщение — прокрутка к нему, как в мессенджере.
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (chat.entries.length) end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); },
    [chat.entries.length, chat.busy]);
  useYumiMood(chat.busy ? "thinking" : chat.error ? "error"
    : chat.entries.at(-1)?.role === "assistant" ? "success" : "idle");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await chat.send(input)) setInput("");
  }
  function upload(event: FormEvent) {
    event.preventDefault();
    if (file) void chat.upload({ file, kind, mapping });
  }
  return <section className="assistant" aria-label="ИИ-ассистент CashCast">
    <div className="assistant-messages" aria-live="polite">
      {!chat.entries.length && <div className="chat-start">
        <b>Спросите Юми о деньгах этого счёта</b>
        <p>Она ответит таблицей или графиком. Ничего не изменит без вашей кнопки «Подтвердить действие».</p>
        <div className="prompts">
          {PROMPTS.map(text => <button type="button" className="ghost" key={text}
            disabled={chat.busy || !enabled} onClick={() => void chat.send(text)}>{text}</button>)}
        </div>
      </div>}
      {chat.entries.map(entry => <article key={entry.id} className={`assistant-message ${entry.role}`}>
        <span className="label">{entry.role === "user" ? "Вы" : "Юми"}</span>
        {entry.role === "assistant" ? <MarkdownMessage text={entry.content} />
          : <p className="assistant-text">{entry.content}</p>}
        {entry.cards.map((card, i) => <ChatCardView key={String(card.data.action_id ?? i)} card={card} api={api}
          companyId={companyId} accountId={accountId} onReply={chat.addReply} />)}
      </article>)}
      {chat.busy && <p role="status">Юми думает…</p>}
      <div ref={end} />
    </div>

    {/* Нижняя закреплённая панель: статус, CSV и ввод — как в мессенджере. */}
    <div className="dock">
      {(chat.error || status.error) && <p role="alert">{chat.error || status.error?.message}</p>}
      {status.data && !enabled && <p className="dock-note"><span className="chip">недоступна</span>
        Ассистент сейчас недоступен. Остальные разделы кабинета работают как обычно.</p>}
      {forecast.stale && <p className="dock-note">Данные изменились — прогноз устарел. Обновите его в разделе «Прогноз».</p>}
      {canWrite && <details className="dock-attach"><summary>Прикрепить CSV в чат</summary><form className="row" onSubmit={upload}>
        <label>Тип CSV<select value={kind} disabled={chat.busy} onChange={e => setKind(e.target.value)}>
          <option value="statement">Банковская выписка</option><option value="obligations">Обязательства</option>
        </select></label><label>Файл для ассистента<input type="file" accept=".csv,text/csv" disabled={chat.busy}
          onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
        <button disabled={chat.busy || !file}>Проверить CSV в чате</button>
        <small>Юми проверит файл. Операции появятся в кабинете только после вашего подтверждения.</small>
        {kind === "statement" && <details><summary>Настройка колонок (для специалистов)</summary>
          <label>JSON колонок для чата<textarea value={mapping} disabled={chat.busy} onChange={e => setMapping(e.target.value)} /></label>
        </details>}
      </form></details>}
      <form className="composer" onSubmit={submit}>
        <label className="sr">Сообщение ассистенту<textarea value={input} maxLength={6000} rows={2}
          disabled={chat.busy} onChange={e => setInput(e.target.value)} placeholder="Спросите Юми: что будет, если клиент задержит оплату?"
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /></label>
        <button disabled={chat.busy || !input.trim() || !enabled}>Отправить ассистенту</button>
      </form>
      <div className="dock-foot">
        <small>Реквизиты платежей Юми не видит. Enter — отправить.</small>
        <button type="button" className="link" disabled={chat.busy || !chat.entries.length} onClick={chat.clear}>Очистить чат</button>
      </div>
    </div>
  </section>;
}
