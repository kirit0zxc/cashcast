// Типы API v1. Пароли и содержимое выписок не сохраняются и не логируются.
export interface Company { id: string; name: string; role: string }
export interface User { id: string; email: string; csrf_token: string; companies: Company[] }
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface Transaction {
  id: string; account_id: string; booked_on: string; amount_minor: number;
  direction: "in" | "out"; currency: string; counterparty_name: string | null;
  purpose: string | null; category: string | null;
}
export interface Preview {
  import_id: string; status: string; total_rows: number; error_count: number;
  duplicate_in_file: number; period_start: string | null; period_end: string | null;
  sample_errors: { row: number; field: string; message: string }[]; reused: boolean;
}
export interface Commit { inserted: number; skipped_existing: number; error_count: number }
export interface PlannedEvent {
  id: string; account_id: string | null; direction: "in" | "out"; amount_minor: number;
  remaining_amount_minor: number; due_date: string; status: string; source: string;
  source_ref: string | null; counterparty_name: string | null; counterparty_ref: string | null;
  provenance: string | null; tax_regime: string | null;
}
export interface ObligationPreview {
  import_id: string; status: string; total_rows: number; valid_count: number; error_count: number;
  sample_errors: { row: number; field: string; code: string }[]; reused: boolean;
}
export interface Accepted { job_id: string; forecast_run_id: string; status: string }
export interface Job { id: string; status: string; error_code: string | null }
export interface Point {
  point_date: string; inflow_minor: number; outflow_minor: number;
  balance_p10_minor: number; balance_p50_minor: number; balance_p90_minor: number;
  probability_negative: number | null;
}
export interface Forecast {
  id: string; as_of: string; model_version: string; data_version: string; status: string;
  opening_balance_minor: number | null; assumptions: string[]; data_warnings: string[];
  risk: { available: boolean; first_negative_date: string | null;
    max_deficit_minor: number | null; probability_any_negative: number | null };
  points: Point[];
}
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
export class CashCastApi {
  constructor(private csrf = "") {}
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.method && init.method !== "GET") headers.set("X-CSRF-Token", this.csrf);
    const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "same-origin" });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(response.status, body?.error?.code ?? "http_error",
        body?.error?.message ?? `Ошибка HTTP ${response.status}`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }
  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request(path, { method: "POST", ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }) });
  }
  patch<T>(path: string, body: unknown): Promise<T> {
    return this.request(path, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
  }
  me() { return this.request<User>("/auth/me"); }
  login(email: string, password: string) { return this.post<User>("/auth/login", { email, password }); }
  logout() { return this.post<void>("/auth/logout"); }
}
// Рубли нужны только при отображении: API и график получают целые копейки.
export const money = (minor: number | null) => minor === null ? "нет данных"
  : new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(minor / 100);
export const probability = (value: number | null) => value === null ? "недоступна"
  : new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 1 }).format(value);

// Десятичная строка превращается в копейки до отправки; лишние знаки не округляем.
export function rublesToMinor(value: string): number {
  if (!/^\d+([.,]\d{1,2})?$/.test(value)) throw new Error("Введите сумму с точностью до копеек");
  const [whole, fraction = ""] = value.replace(",", ".").split(".");
  const minor = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  if (!Number.isSafeInteger(minor) || minor <= 0 || minor > 9_000_000_000_000_000) {
    throw new Error("Сумма вне допустимого диапазона");
  }
  return minor;
}
