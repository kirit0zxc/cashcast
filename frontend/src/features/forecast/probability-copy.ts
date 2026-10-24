import type { Forecast } from "../../shared/api";

// Почему процента нет — человеческим языком. Причины берём из версии модели и
// предупреждений качества, которые сервер сохранил вместе с расчётом.
export type ProbabilityGap = { reason: string; fix: "recalculate" | "import" | null };

export function probabilityGap(f: Pick<Forecast, "model_version" | "data_warnings" | "risk">): ProbabilityGap | null {
  if (f.risk.probability_any_negative != null) return null;
  if (!f.model_version.includes("estimated")) {
    return { reason: "Этот расчёт сделан прежней версией модели, она не оценивала риск в процентах.", fix: "recalculate" };
  }
  const w = f.data_warnings.join(" ");
  if (/устарел/.test(w)) {
    return { reason: "Последние данные по счёту старше 3 дней. Загрузите свежую выписку или рассчитайте прогноз на её последний день.", fix: "import" };
  }
  if (/Менее\s*28|Менее\s*56/.test(w)) {
    return { reason: "Мало истории: для оценки риска нужно не меньше 56 дней операций.", fix: "import" };
  }
  if (/несверк|не согласуется/.test(w)) {
    return { reason: "Остаток в выписке не сходится с операциями, поэтому риск не оцениваем.", fix: "import" };
  }
  return { reason: "Данных недостаточно для оценки риска.", fix: null };
}

/** 0,18 → «в 18 из 100 вариантов». */
export function outOfHundred(value: number) {
  const n = Math.round(value * 100);
  return n === 0 ? "ни в одном из 100 вариантов будущего" : `в ${n} из 100 вариантов будущего`;
}
