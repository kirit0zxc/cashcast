import type { Forecast } from "../../shared/api";

// Бинарное предупреждение новой модели не подменяет процент старого прогноза.
export function MLRiskFlag({ forecast }: { forecast: Forecast }) {
  const assessment = forecast.risk.ml_flag;
  if (!assessment) return null;
  const ready = assessment.available && typeof assessment.flag === "boolean";
  const reason = assessment.reason === "model_unavailable" ? "Сервис временно недоступен."
    : assessment.reason === "scenario_not_supported" ? "Изменения сценария этим детектором не оцениваются."
      : "Нужны 84 дня согласованной истории, неотрицательный остаток и прогноз на 30 дней.";
  return <div className={ready && assessment.flag ? "errors" : "note"} data-testid="ml-risk-flag" role="status">
    <strong>ML-детектор: риск разрыва — {ready ? assessment.flag ? "да" : "нет" : "не оценено"}.</strong>
    <p>{ready ? "По истории операций на следующие 30 дней. Планы и сценарии не учитываются. Сигнал может ошибаться."
      : reason} Процент выше рассчитывает основная прогнозная модель.</p>
  </div>;
}
