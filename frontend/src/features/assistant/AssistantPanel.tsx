import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useAccount } from "../../app/account-context";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { Aura } from "../../ui/Aura";
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
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await chat.send(input)) setInput("");
  }
  function upload(event: FormEvent) {
    event.preventDefault();
    if (file) void chat.upload({ file, kind, mapping });
  }
  return <section className="assistant" aria-label="ИИ-ассистент CashCast">
    <div className="assistant-head">
      <div className="avatar"><Aura tone="assistant" cell={4} /></div>
      <div>
        <span className="label">ИИ-ассистент</span>
        <h2>Юми</h2>
        <p>Отвечает на вопросы о деньгах этого счёта. Ничего не меняет без вашей кнопки «Подтвердить действие».</p>
      </div>
      <div className="assistant-status">
        {status.isPending && <span className="chip">проверяем…</span>}
        {status.data && <span className={`chip${enabled ? " solid" : ""}`}>{enabled ? "на связи" : "недоступна"}</span>}
      </div>
    </div>
    <p className="note">Реквизиты и назначения платежей ассистенту не показываются. Не пишите в чат пароли и личные данные.</p>
    {status.data && !enabled && <div className="empty"><b>Ассистент сейчас недоступен</b>
      Остальные разделы кабинета работают как обычно.</div>}
    {status.error && <p role="alert">{status.error.message}</p>}
    {forecast.stale && <p className="note">Данные изменились — прогноз устарел. Обновите его кнопкой «Рассчитать» в разделе «Прогноз».</p>}

    <div className="prompts">
      {PROMPTS.map(text => <button type="button" className="ghost" key={text}
        disabled={chat.busy || !enabled} onClick={() => void chat.send(text)}>{text}</button>)}
    </div>

    <div className="assistant-messages" aria-live="polite">
      {!chat.entries.length && <div className="empty"><b>Чат пуст</b>Задайте вопрос или выберите подсказку выше.</div>}
      {chat.entries.map(entry => <article key={entry.id} className={`assistant-message ${entry.role}`}>
        <span className="label">{entry.role === "user" ? "Вы" : "Юми"}</span>
        {entry.role === "assistant" ? <MarkdownMessage text={entry.content} />
          : <p className="assistant-text">{entry.content}</p>}
        {entry.cards.map((card, i) => <ChatCardView key={String(card.data.action_id ?? i)} card={card} api={api}
          companyId={companyId} accountId={accountId} onReply={chat.addReply} />)}
      </article>)}
      {chat.busy && <p role="status">Юми думает…</p>}
    </div>
    {chat.error && <p role="alert">{chat.error}</p>}

    <form className="composer" onSubmit={submit}>
      <label>Сообщение ассистенту<textarea value={input} maxLength={6000} rows={3}
        disabled={chat.busy} onChange={e => setInput(e.target.value)} placeholder="Что будет, если клиент задержит оплату?" /></label>
      <div className="row">
        <button disabled={chat.busy || !input.trim() || !enabled}>Отправить ассистенту</button>
        <button type="button" className="ghost" disabled={chat.busy || !chat.entries.length} onClick={chat.clear}>Очистить чат</button>
      </div>
    </form>
    {canWrite && <details className="panel dash"><summary>Прикрепить CSV в чат</summary><form className="row" onSubmit={upload}>
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
  </section>;
}
