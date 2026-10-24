import { useQuery } from "@tanstack/react-query";
import { navigate } from "../../app/router";
import { CashCastApi, money, probability } from "../../shared/api";
import { dayMonth } from "../../ui/Blank";
import type { CashGapReport } from "./cash-gaps";

// Главный вывод карточки разрыва — коротко и наверху обзора. Тот же сохранённый отчёт
// и тот же ключ кэша, что у CashGapPanel: новых запросов к расчёту нет, только чтение.
export function GapBanner({ api, forecastId }: { api: CashCastApi; forecastId: string }) {
  const query = useQuery({ queryKey: ["cash-gaps", forecastId], retry: false,
    queryFn: ({ signal }) => api.request<CashGapReport>(`/forecasts/${forecastId}/cash-gaps`, { signal }) });
  const r = query.data;
  if (!r) return null; // Отчёт недоступен — ниже на обзоре остаются кривая и предупреждения.
  const b = r.base;
  const reserve = b.required_reserve_minor ?? b.max_deficit_minor;
  const tone = b.status === "gap" ? "risk" : b.status === "no_gap" ? "ok" : "unknown";
  const title = b.status === "no_gap" ? "На этот период денег хватает"
    : b.status === "insufficient_data" ? "Данных мало, чтобы исключить разрыв"
      : b.opening_already_negative ? `Деньги уже в минусе: не хватает ${money(b.max_deficit_minor)}`
        : b.days_until_new_gap != null ? `Через ${b.days_until_new_gap} дн. может не хватить ${money(b.max_deficit_minor)}`
          : `Может не хватить ${money(b.max_deficit_minor)}`;
  return <section className={`gap-banner tone-${tone}`} aria-label="Кассовый разрыв">
    <div>
      <span className="label">Кассовый разрыв</span>
      <b>{title}</b>
      {b.status === "gap" && <p>
        {b.first_new_gap_date && <>Первый день в минусе — {dayMonth(b.first_new_gap_date)}. </>}
        Чтобы не уйти в минус, нужен резерв <strong>{money(reserve)}</strong>.
        {r.probability != null && <> Риск по модели — {probability(r.probability)} (оценка).</>}
      </p>}
      {b.status === "no_gap" && <p>По прогнозу остаток не уходит ниже нуля до {dayMonth(r.horizon_end)}.</p>}
      {b.status === "insufficient_data" && <p>Загрузите выписку подлиннее — тогда прогноз сможет это проверить.</p>}
    </div>
    {b.status === "gap" && <button type="button" onClick={() => openCashGaps()}>Что можно сделать</button>}
  </section>;
}

// Переход к карточке разрыва в «Прогнозе» с прокруткой к ней.
export function openCashGaps() {
  navigate("/forecast");
  let tries = 0;
  const find = () => {
    const panel = document.querySelector('[data-testid="cash-gap-panel"]');
    if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
    else if (tries++ < 40) window.setTimeout(find, 100);
  };
  window.setTimeout(find, 50);
}
