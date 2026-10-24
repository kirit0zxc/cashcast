import { Link, navigate } from "../../app/router";
import { useAccount } from "../../app/account-context";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import type { Forecast } from "../../shared/api";
import { outOfHundred, probabilityGap } from "./probability-copy";

// Число описывает симуляцию модели; калибровку нельзя подразумевать по наличию процента.
export function ProbabilityNotice({ forecast }: { forecast: Forecast }) {
  const { forecast: c } = useAccount();
  const canWrite = useCompanyCanWrite();
  const value = forecast.risk.probability_any_negative;
  if (value != null) {
    return <p className="note" data-testid="probability-notice">
      Риск уйти в минус: деньги заканчиваются хотя бы на один день {outOfHundred(value)}.
      {" "}Это модельная оценка, не откалибрована: 0% и 100% — не гарантия.
      {" "}<Link to="/quality">Насколько точен прогноз →</Link></p>;
  }
  const gap = probabilityGap(forecast);
  return <div className="note prob-gap" data-testid="probability-notice">
    <p>Риск в процентах сейчас не оценивается — это не 0%. {gap?.reason}
      {" "}Даты и суммы возможного минуса показываются всё равно.
      {" "}<Link to="/quality">Насколько точен прогноз →</Link></p>
    {canWrite && gap?.fix === "recalculate" && <button type="button" className="ghost" disabled={c.working}
      onClick={c.run}>Пересчитать с оценкой риска</button>}
    {canWrite && gap?.fix === "import" && <button type="button" className="ghost"
      onClick={() => navigate("/import")}>Загрузить выписку</button>}
  </div>;
}
