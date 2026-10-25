// Типы ответа «Финансового пульса» (pulse-cashcast-1.0) для фронтенда CashCast.
// Источник истины — backend/app/api/schemas/pulse.py и specs/openapi.json.
// Деньги — целые копейки (*_minor), даты — строки YYYY-MM-DD.

export type Status = "ok" | "watch" | "risk" | "unknown";
export type Urgency = "now" | "this_month" | "later";

export interface PulseReport {
  forecast_id: string;
  account_id: string;
  model_version: string;
  data_version: string;
  company_id: string;
  as_of: string;
  method_version: string;
  status: Status; // худший из трёх блоков — цвет общей плашки
  headline: string; // одна-две фразы для шапки экрана
  cash: CashBlock;
  money: MoneyBlock;
  clients: ClientsBlock;
  actions: PulseAction[]; // до 5, уже отсортированы: сначала «сейчас»
  warnings: string[]; // качество данных: показывать мелко
}

export interface CashBlock {
  status: Status;
  message: string;
  first_gap_date: string | null;
  days_until_gap: number | null;
  max_deficit_minor: number;
  gap_only_if_owner_withdraws: boolean; // разрыв будет, только если выводить деньги как обычно
  structural_shortfall: boolean; // расходы стабильно выше доходов — перенос не спасёт
  buffer_minor: number; // безопасный запас (подушка)
  buffer_source: "user" | "auto";
  plan: CashPlan | null;
  suggestions: { title: string; details: string[] }[];
  chart: {
    days: string[]; // 30 дней после as_of
    base_minor: number[]; // прогноз без вывода денег владельцем
    if_owner_withdraws_minor: number[] | null; // «если выводить как обычно»
    after_plan_minor: number[] | null; // после шагов плана
    buffer_minor: number; // горизонтальная линия запаса
  };
  warnings: string[];
  assumptions: string[];
}

export interface CashPlan {
  title: string;
  resolved: boolean;
  steps: { title: string; amount_minor: number; cost_minor: number; details: string[] }[];
  credit_minor: number;
  credit_cost_minor: number;
  holds_if_inflows_drop_20pct: boolean;
}

export interface MoneyBlock {
  status: Status;
  loss_per_year_minor: number; // теряете в год (факты)
  opportunity_per_year_minor: number; // можно заработать в год (оценки)
  opportunity_deferred_minor: number; // отложено из-за возможной нехватки
  one_off_loss_minor: number; // разовые потери за последний год (взыскания, двойные платежи)
  frozen_minor: number; // деньги, временно застрявшие из-за ошибок в реквизитах
  signals: number; // сколько сигналов «проверьте»
  findings: MoneyFinding[];
  assumptions: string[];
  warnings: string[];
}

export interface MoneyFinding {
  kind:
    | "idle_cash"
    | "card_rate_above_peers"
    | "sbp_shift"
    | "price_creep"
    | "overdraft_interest"
    | "forced_collections"
    | "possible_duplicates"
    | "account_fee_above_peers"
    | "wrong_requisites";
  nature: "loss" | "opportunity" | "signal" | "frozen";
  certainty: "fact" | "estimate"; // показывать меткой «факт» / «оценка»
  title: string;
  amount_minor: number;
  period: "year" | "window"; // «в год» или «за последний год»
  evidence: string[]; // доказательства — раскрывающийся список
  action: string; // что сделать
  blocked_by_cash_gap: boolean; // совет отложен: впереди возможная нехватка
}

export interface ClientsBlock {
  applicable: boolean; // false — нет B2B-клиентов (эквайринг/СБП), блок можно свернуть
  status: Status;
  message: string;
  top_client: { name: string; share: number; grade: string; grade_label: string } | null;
  at_risk: { name: string; grade: string; grade_label: string; share: number; reasons: string[] }[];
  stress: {
    title: string;
    text: string;
    kind: "delay" | "loss";
    first_gap_date: string | null;
    creates_gap: boolean;
    worst_day_shortfall_minor: number;
    basis: string;
  }[];
}

export interface PulseAction {
  urgency: Urgency;
  title: string;
  why: string;
  amount_minor: number;
  source: "cash" | "money" | "clients";
}

export const formatRub = (minor: number): string =>
  new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 })
    .format(minor / 100);
