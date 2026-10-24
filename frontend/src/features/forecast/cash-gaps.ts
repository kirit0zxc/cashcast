// Дополнительный frozen-отчёт: суммы в копейках, даты ISO; null не означает 0%.
export interface GapSummary {
  status: "gap" | "no_gap" | "insufficient_data";
  opening_already_negative: boolean; first_new_gap_date: string | null;
  days_until_new_gap?: number | null; required_reserve_minor?: number;
  max_deficit_minor: number; total_negative_days: number;
  episodes: { kind: "existing" | "new"; first_negative_date: string; last_negative_date: string;
    recovery_date: string | null; observed_days: number; duration_is_lower_bound: boolean;
    max_deficit_minor: number; worst_date: string }[];
}
export interface CashGapReport {
  forecast_id: string; as_of: string; horizon_end: string; base: GapSummary; preview: GapSummary;
  points: { date: string; base_minor: number; preview_minor: number; delta_minor: number }[];
  flows: { id: string; date: string; amount_minor: number; label: string; delay_allowed: boolean }[];
  causes: { date: string; amount_minor: number; label: string; evidence: string; source_ref: string | null }[];
  causes_date: string; causes_balance_minor: number; probability_reason: string;
  probability?: number | null; probability_status?: "unavailable" | "estimated_uncalibrated";
  quality_mode: string; improvement_minor: number; financing_cost_minor: number;
  debt_beyond_horizon_minor: number; warnings: string[];
}
export type GapAction = { kind: "delay"; flow_id: string; to_date: string; payment_delay_agreed: boolean }
  | { kind: "financing"; date: string; amount_minor: number; repayment_date: string; cost_minor: number };
