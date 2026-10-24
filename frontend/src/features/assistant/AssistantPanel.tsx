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
    queryFn: ({ signal }) => api.request<{ enabled: boolean; model: string }>("/assistant/status", { signal }) });
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
        <span className="label">09 · ИИ-ассистент · срез {forecast.asOf}</span>
        <h2>Юми</h2>
        <p>Объясняет данные выбранного счёта, показывает графики и предлагает действия.
          Все изменения — только после кнопки «Подтвердить действие».</p>
      </div>
      <div className="assistant-status">
        {status.isPending && <span className="chip">проверяем…</span>}
        {status.data && <span className={`chip${enabled ? " solid" : ""}`}>{enabled ? "включён" : "выключен"}</span>}
        {status.data && <small className="mono">{status.data.model}</small>}
      </div>
    </div>
    <p className="note">Сообщения и необходимые финансовые показатели передаются DeepSeek через OpenRouter.
      Реквизиты и исходные назначения из базы скрываются. Не вводите пароли и ключи.</p>
    {status.data && !enabled && <div className="empty"><b>Ассистент недоступен</b>
      Ключ модели на сервере не настроен. Остальные разделы кабинета работают без него.</div>}
    {status.error && <p role="alert">{status.error.message}</p>}
    {forecast.stale && <p className="note">Данные изменены подтверждённым действием — прогноз устарел. Новый расчёт — кнопкой «Рассчитать» или отдельным предложением ассистента.</p>}

    <div className="prompts">
      {PROMPTS.map(text => <button type="button" className="ghost" key={text}
        disabled={chat.busy || !enabled} onClick={() => void chat.send(text)}>{text}</button>)}
    </div>

    <div className="assistant-messages" aria-live="polite">
      {!chat.entries.length && <div className="empty"><b>Чат пуст</b>Спросите о деньгах счёта или выберите подсказку выше.
        История сохраняется при переходах между разделами и сбрасывается при смене счёта.</div>}
      {chat.entries.map(entry => <article key={entry.id} className={`assistant-message ${entry.role}`}>
        <span className="label">{entry.role === "user" ? "Вы" : "Юми · CashCast"}</span>
        {entry.role === "assistant" ? <MarkdownMessage text={entry.content} />
          : <p className="assistant-text">{entry.content}</p>}
        {entry.cards.map((card, i) => <ChatCardView key={String(card.data.action_id ?? i)} card={card} api={api}
          companyId={companyId} accountId={accountId} onReply={chat.addReply} />)}
      </article>)}
      {chat.busy && <p role="status">Ассистент получает данные…</p>}
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
      <small>Для выписки используется формат организаторов: «;» и UTF-8 BOM. Файл остаётся на сервере CashCast,
        модели он не передаётся; операции появятся только после подтверждения.</small>
      {kind === "statement" && <details><summary>Другое соответствие колонок</summary>
        <label>JSON колонок для чата<textarea value={mapping} disabled={chat.busy} onChange={e => setMapping(e.target.value)} /></label>
      </details>}
    </form></details>}
  </section>;
}
