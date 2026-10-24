import { createContext, useContext, type ReactNode } from "react";

// Роль относится к выбранной компании. Отсутствие provider не даёт права записи;
// окончательное решение всегда принимает сервер, включая устаревшую сессию.
const CompanyWriteContext = createContext(false);
export function CompanyPermission({ role, children }: { role?: string; children: ReactNode }) {
  return <CompanyWriteContext.Provider value={role === "owner"}>{children}</CompanyWriteContext.Provider>;
}
export function useCompanyCanWrite() { return useContext(CompanyWriteContext); }
