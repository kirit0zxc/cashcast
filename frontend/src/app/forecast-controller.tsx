import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { CashCastApi, type Accepted, type Forecast, type ForecastHistoryEntry, type Job, type Page } from "../shared/api";

const today = () => new Date().toISOString().slice(0, 10);
const terminal = (status?: string) => status === "succeeded" || status === "failed";

// Что сейчас выбрано: последний сохранённый базовый расчёт, явный расчёт или ничего
// (пользователь сменил дату среза и ещё не запускал расчёт).
type Selection =
  | { mode: "latest" }
  | { mode: "none" }
  | { mode: "run"; id: string; jobId: string | null; errorCode?: string | null };

export interface ForecastController {
  asOf: string;
  selection: Selection;
  runId: string | undefined;
  jobId: string | null | undefined;
  job: UseQueryResult<Job>;
  forecast: UseQueryResult<Forecast>;
  /** Запрос на постановку задания ещё не принят сервером. */
  requesting: boolean;
  /** Задание отправлено или выполняется на worker. */
  working: boolean;
  errors: Error[];
  /** Дата среза изменена вручную: прежний результат больше не показывается. */
  changeDate: (date: string) => void;
  /** Ручной расчёт по кнопке. */
  run: () => void;
  /** Событие успешной записи данных: один вызов — один POST, вкладка прогноза может быть закрыта. */
  dataChanged: (date?: string) => void;
  /** Открыть сохранённый расчёт без нового задания. */
  open: (entry: Pick<ForecastHistoryEntry, "id" | "as_of" | "job_id" | "error_code">) => void;
  /** Данные изменены подтверждённым действием ассистента: показанный прогноз устарел. */
  stale: boolean;
  markStale: () => void;
}

// Один контроллер на выбранный счёт. Живёт выше страниц, поэтому переход по меню
// не сбрасывает выбор и не создаёт задание. Пересчёт запускается событием мутации,
// а не remount-ом: обработчики событий React не повторяются в StrictMode.
export function useForecastController({ api, companyId, accountId, canWrite }: {
  api: CashCastApi; companyId: string; accountId: string; canWrite: boolean;
}): ForecastController {
  const cache = useQueryClient();
  const [asOf, setAsOf] = useState(today);
  const [selection, setSelection] = useState<Selection>({ mode: "latest" });
  // Ассистент не запускает скрытый пересчёт: только отмечает, что прогноз устарел.
  const [stale, setStale] = useState(false);
  // Последний отправленный запрос; поздний ответ прежнего запроса игнорируется.
  const sequence = useRef(0);

  const latest = useQuery({
    queryKey: ["forecast-history", companyId, accountId, "latest-base"],
    queryFn: ({ signal }) => api.request<Page<ForecastHistoryEntry>>(
      `/companies/${companyId}/forecasts?account_id=${accountId}&limit=10`, { signal }),
    enabled: selection.mode === "latest",
  });
  const latestEntry = latest.data?.items.find(item => item.status === "succeeded" && !item.base_forecast_id);

  const runId = selection.mode === "run" ? selection.id : selection.mode === "latest" ? latestEntry?.id : undefined;
  const jobId = selection.mode === "run" ? selection.jobId : undefined;
  const effectiveAsOf = selection.mode === "latest" && latestEntry ? latestEntry.as_of : asOf;

  const mutation = useMutation({
    mutationFn: ({ date }: { date: string; seq: number }) => api.post<Accepted>(`/companies/${companyId}/forecasts`, {
      account_id: accountId, as_of: date, horizon_days: 30,
    }),
    onSuccess: async (data, { seq }) => {
      if (seq !== sequence.current) return;
      setSelection({ mode: "run", id: data.forecast_run_id, jobId: data.job_id });
      // Enqueue может выполнить auto-reconcile. Явный recovery может вернуть тот же ID после cached failed.
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["job", data.job_id] }),
        cache.invalidateQueries({ queryKey: ["forecast", data.forecast_run_id] }),
        cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] }),
        cache.invalidateQueries({ queryKey: ["plan-fact", companyId, accountId] }),
        cache.invalidateQueries({ queryKey: ["forecast-history", companyId, accountId] }),
      ]);
    },
  });
  const { mutate, reset } = mutation;

  const enqueue = useCallback((date: string) => {
    sequence.current += 1;
    setAsOf(date);
    setSelection({ mode: "none" });
    setStale(false);
    mutate({ date, seq: sequence.current });
  }, [mutate]);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.request<Job>(`/jobs/${jobId}`, { signal }),
    enabled: !!jobId,
    refetchInterval: query => terminal(query.state.data?.status) ? false : 1500,
  });
  const forecast = useQuery({
    queryKey: ["forecast", runId],
    queryFn: ({ signal }) => api.request<Forecast>(`/forecasts/${runId}`, { signal }),
    enabled: !!runId && (!jobId || job.error !== null || terminal(job.data?.status)),
  });

  const working = mutation.isPending || (!!jobId && !job.error && !terminal(job.data?.status));
  const errors = [mutation.error, job.error, forecast.error, selection.mode === "latest" ? latest.error : null]
    .filter((e): e is Error => e instanceof Error);

  return {
    asOf: effectiveAsOf, selection, runId, jobId, job, forecast, working, errors, stale,
    markStale: () => setStale(true),
    requesting: mutation.isPending,
    changeDate: date => {
      sequence.current += 1;
      reset(); setAsOf(date); setSelection({ mode: "none" });
    },
    run: () => { if (canWrite) enqueue(effectiveAsOf); },
    dataChanged: date => { if (canWrite) enqueue(date ?? effectiveAsOf); },
    open: entry => {
      sequence.current += 1;
      reset(); setAsOf(entry.as_of); setStale(false);
      setSelection({ mode: "run", id: entry.id, jobId: entry.job_id, errorCode: entry.error_code });
    },
  };
}
