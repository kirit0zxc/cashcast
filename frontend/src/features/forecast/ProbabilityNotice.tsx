import type { Forecast } from "../../shared/api";

// Число описывает симуляцию модели; калибровку нельзя подразумевать по наличию процента.
export function ProbabilityNotice({ forecast }: { forecast: Forecast }) {
  return forecast.risk.probability_any_negative != null
    ? <p className="note" data-testid="probability-notice">Модельная оценка, не откалибрована.
      {" "}Общий процент — доля вариантов с минусом хотя бы в один будущий день,
      дневной — доля вариантов с минусом в указанную дату. 0% и 100% не являются гарантией.</p>
    : null;
}
