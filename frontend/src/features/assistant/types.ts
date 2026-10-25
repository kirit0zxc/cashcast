// Карточки создаёт сервер из результатов API. Произвольный HTML от модели не исполняется.
export interface ChatCard {
  kind: "forecast" | "comparison" | "pulse" | "table" | "action" | "job" | "import";
  title: string; data: Record<string, unknown>;
}
export interface ChatReply { text: string; cards: ChatCard[]; error_code?: string | null }
export interface ChatEntry { id: string; role: "user" | "assistant"; content: string; cards: ChatCard[] }
