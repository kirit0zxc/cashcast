import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { CashCastApi } from "../../shared/api";
import type { ForecastController } from "../../app/forecast-controller";
import type { ChatCard, ChatEntry, ChatReply } from "./types";

interface Retry { request_id: string; messages: { role: string; content: string }[]; text: string; asOf: string }

export interface AssistantChat {
  entries: ChatEntry[];
  busy: boolean;
  error: string;
  send: (text: string) => Promise<boolean>;
  upload: (form: { file: File; kind: string; mapping: string }) => Promise<void>;
  /** Ответ сервера на подтверждение или отмену карточки действия. */
  addReply: (reply: ChatReply, confirmed: ChatCard | null) => void;
  clear: () => void;
}

// История чата живёт в AccountProvider, а не в странице: переход между разделами
// её не теряет, смена счёта/компании и выход размонтируют провайдер и сбрасывают её.
// Перезагрузка страницы тоже сбрасывает чат — серверную историю не обещаем.
export function useAssistantChat({ api, companyId, accountId, forecast }: {
  api: CashCastApi; companyId: string; accountId: string; forecast: ForecastController;
}): AssistantChat {
  const cache = useQueryClient();
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  // Сетевой повтор того же сообщения отправляет прежний request_id и неизменное тело.
  const retry = useRef<Retry | null>(null);

  function addReply(reply: ChatReply, confirmed: ChatCard | null) {
    // Итоговый статус предложения записываем и в исходную карточку: после перехода
    // между разделами она не должна снова показывать «ожидает» и активные кнопки.
    const decided = new Map(reply.cards.filter(card => card.kind === "action")
      .map(card => [String(card.data.action_id), card.data.status]));
    setEntries(old => [...old.map(entry => !entry.cards.some(card => decided.has(String(card.data.action_id))) ? entry
      : { ...entry, cards: entry.cards.map(card => card.kind === "action" && decided.has(String(card.data.action_id))
        ? { ...card, data: { ...card.data, status: decided.get(String(card.data.action_id)) } } : card) }),
    { id: crypto.randomUUID(), role: "assistant", content: reply.text, cards: reply.cards }]);
    if (!confirmed) return;
    // Подтверждённое действие уже записано сервером: обновляем все разделы.
    void cache.invalidateQueries();
    const name = String(confirmed.data.name ?? "");
    const result = reply.cards.find(card => card.kind === "job")?.data;
    if (name === "propose_forecast" && result?.forecast_run_id) {
      // Расчёт уже поставлен подтверждённым действием — открываем его, без второго POST.
      const args = confirmed.data.arguments as { as_of?: string } | undefined;
      forecast.open({ id: String(result.forecast_run_id), job_id: String(result.job_id),
        as_of: args?.as_of ?? forecast.asOf, error_code: null });
    } else if (name !== "propose_scenario") {
      forecast.markStale();
    }
  }

  async function send(text: string) {
    if (active.current || !text.trim()) return false;
    active.current = true; setBusy(true); setError("");
    if (!retry.current || retry.current.text !== text) {
      const history = entries.slice(-10).map(entry => ({ role: entry.role, content: (entry.content +
        (entry.cards.length ? "\nКарточки: " + entry.cards.map(c => JSON.stringify({ title: c.title,
          forecast_id: c.kind === "forecast" ? c.data.id : c.data.forecast_run_id ?? c.data.forecast_id,
          next_cursor: c.data.next_cursor })).join("; ") : "")).slice(0, 6000) }));
      retry.current = { request_id: crypto.randomUUID(), text, asOf: forecast.asOf,
        messages: [...history, { role: "user", content: text }] };
      setEntries(old => [...old, { id: crypto.randomUUID(), role: "user", content: text, cards: [] }]);
    }
    try {
      const reply = await api.post<ChatReply>(`/companies/${companyId}/assistant/chat`, {
        request_id: retry.current.request_id, account_id: accountId, as_of: retry.current.asOf, messages: retry.current.messages,
      });
      retry.current = null; addReply(reply, null);
      if (reply.error_code) setError(reply.text);
      return true;
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось отправить сообщение"); return false; }
    finally { active.current = false; setBusy(false); }
  }

  async function upload({ file, kind, mapping }: { file: File; kind: string; mapping: string }) {
    if (active.current) return;
    active.current = true; setBusy(true); setError("");
    const form = new FormData(); form.set("file", file); form.set("import_kind", kind); form.set("as_of", forecast.asOf);
    if (mapping.trim() && kind === "statement") form.set("mapping", mapping);
    try {
      addReply(await api.request<ChatReply>(`/companies/${companyId}/accounts/${accountId}/assistant/uploads`,
        { method: "POST", body: form }), null);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось проверить CSV"); }
    finally { active.current = false; setBusy(false); }
  }

  return { entries, busy, error, send, upload, addReply,
    clear: () => { setEntries([]); retry.current = null; setError(""); } };
}
