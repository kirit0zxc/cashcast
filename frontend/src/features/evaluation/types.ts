// Отчёт текущего датасета, отдельно от исторических исследовательских метрик.
export interface Metric { value: number | null; unavailable_reason: string | null }
export interface Classification {
  n: number; threshold: number;
  confusion_matrix: { tp: number; fp: number; fn: number; tn: number };
  metrics: Record<string, Metric>;
}
export interface EvaluationPoint {
  date: string; balance_p10_minor: number; balance_p50_minor: number; balance_p90_minor: number;
  inflow_minor: number; outflow_minor: number; actual_balance_minor: number | null;
  actual_inflow_minor: number | null; actual_outflow_minor: number | null;
  probability_negative: number | null; balance_source: "observed" | "reconstructed" | "missing";
  components: Record<string, number>;
}
export interface EvaluationWindow {
  index: number; as_of: string; status: "succeeded" | "skipped"; reason?: string;
  points: EvaluationPoint[]; probability_any_negative?: number | null; warnings?: string[];
}
export interface EvaluationReport {
  model_version: string; dataset_sha256: string; source_sha256: string | null;
  config: { threshold: number; seed: number; complete_statement: boolean; horizon_days: number; folds: number; as_of: string };
  regression: Record<string, { n: number; mae: Metric; mse: Metric; rmse: Metric }>;
  daily_median_negative: Classification; daily_probability_negative: Classification; horizon_new_gap: Classification;
  interval_coverage: Metric; windows: EvaluationWindow[]; trace: { step: string; message: string }[]; limitations: string[];
}
export interface EvaluationJob {
  id: string; status: "pending" | "running" | "succeeded" | "failed"; error_code: string | null;
  report: EvaluationReport | null;
}
