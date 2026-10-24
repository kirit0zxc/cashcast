import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { CashCastApi } from "../shared/api";
import { useCompanyCanWrite } from "../shared/company-permissions";
import { useForecastController, type ForecastController } from "./forecast-controller";
import { useAssistantChat, type AssistantChat } from "../features/assistant/chat";

const today = () => new Date().toISOString().slice(0, 10);

export interface AccountContextValue {
  api: CashCastApi;
  companyId: string;
  accountId: string;
  forecast: ForecastController;
  /** Видимая история чата ассистента для этого счёта. */
  assistant: AssistantChat;
  /** Выписка сохранена: обновить операции и пересчитать прогноз на конец периода. */
  statementCommitted: (periodEnd: string | null) => void;
  /** Изменились планы или применена сверка: пересчёт на сегодняшний срез. */
  plansChanged: () => void;
  /** Ручная категория: пересчёт на выбранный срез. */
  categoryChanged: () => void;
}

const AccountContext = createContext<AccountContextValue | null>(null);

// Провайдер монтируется с key={accountId}: смена счёта или компании сбрасывает
// выбор расчёта, курсоры и формы страниц.
export function AccountProvider({ api, companyId, accountId, children }: {
  api: CashCastApi; companyId: string; accountId: string; children: ReactNode;
}) {
  const cache = useQueryClient();
  const canWrite = useCompanyCanWrite();
  const forecast = useForecastController({ api, companyId, accountId, canWrite });
  const assistant = useAssistantChat({ api, companyId, accountId, forecast });
  const value: AccountContextValue = {
    api, companyId, accountId, forecast, assistant,
    statementCommitted: periodEnd => {
      void cache.invalidateQueries({ queryKey: ["transactions", companyId, accountId] });
      forecast.dataChanged(periodEnd ?? undefined);
    },
    plansChanged: () => forecast.dataChanged(today()),
    categoryChanged: () => forecast.dataChanged(),
  };
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount(): AccountContextValue {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useAccount вызван вне AccountProvider");
  return value;
}
