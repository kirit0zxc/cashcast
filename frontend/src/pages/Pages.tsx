import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useAccount } from "../app/account-context";
import { ASSISTANT_ROUTE, ROUTES, type RoutePath } from "../app/router";
import { ForecastPanel, ForecastState } from "../features/forecast/ForecastPanel";
import { ScenarioPanel } from "../features/forecast/ScenarioPanel";
import { StatementImport } from "../features/imports/StatementImport";
import { ObligationImport } from "../features/planning/ObligationImport";
import { PlanFactPanel } from "../features/planning/PlanFactPanel";
import { PlannedEvents } from "../features/planning/PlannedEvents";
import { PulsePanel } from "../features/pulse/PulsePanel";
import { Transactions } from "../features/transactions/Transactions";
import { useCompanyCanWrite } from "../shared/company-permissions";
import { Empty } from "../ui/Empty";
import { OverviewPage } from "./OverviewPage";

// Переключение раздела только меняет видимую страницу: данные и выбранный расчёт
// живут в AccountProvider, поэтому переход не отправляет POST и не создаёт job.
export function Pages({ route }: { route: RoutePath }) {
  switch (route) {
    case "/overview": return <OverviewPage />;
    case "/operations": return <Page route={route}><OperationsPage /></Page>;
    case "/import": return <Page route={route}><ImportPage /></Page>;
    case "/payments": return <Page route={route}><PaymentsPage /></Page>;
    case "/reconciliation": return <Page route={route}><ReconciliationPage /></Page>;
    case "/forecast": return <Page route={route}><ForecastPanel /></Page>;
    case "/scenarios": return <Page route={route}><ScenariosPage /></Page>;
    case "/pulse": return <Page route={route}><PulsePage /></Page>;
    case "/assistant": return <Page route={route}><AssistantPage /></Page>;
  }
}

function Page({ route, children }: { route: RoutePath; children: ReactNode }) {
  const index = ROUTES.findIndex(r => r.path === route);
  const title = index >= 0 ? ROUTES[index].title : ASSISTANT_ROUTE.title;
  return <>
    <div className="page-title"><span className="label">Раздел {String(index >= 0 ? index + 1 : 9).padStart(2, "0")}</span>
      <h1>{title}</h1></div>
    {children}
  </>;
}

function OperationsPage() {
  const { api, companyId, accountId, categoryChanged } = useAccount();
  return <Transactions api={api} companyId={companyId} accountId={accountId} onChanged={categoryChanged} />;
}

function ImportPage() {
  const { api, companyId, accountId, statementCommitted, plansChanged } = useAccount();
  const canWrite = useCompanyCanWrite();
  const cache = useQueryClient();
  if (!canWrite) return <Empty title="Импорт доступен владельцу компании" text="В режиме чтения можно смотреть операции и сохранённые расчёты." />;
  return <>
    <StatementImport api={api} companyId={companyId} accountId={accountId} onCommit={statementCommitted} />
    <section className="panel dash"><h2>Счета и обязательства</h2>
      <ObligationImport api={api} companyId={companyId} accountId={accountId} onChanged={async () => {
        await cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] });
        plansChanged();
      }} />
    </section>
  </>;
}

function PaymentsPage() {
  const { api, companyId, accountId, plansChanged } = useAccount();
  return <PlannedEvents api={api} companyId={companyId} accountId={accountId} onChanged={plansChanged} />;
}

function ReconciliationPage() {
  const { api, companyId, accountId, plansChanged } = useAccount();
  return <PlanFactPanel api={api} companyId={companyId} accountId={accountId} onApplied={plansChanged} />;
}

// Сценарий строится от выбранной сохранённой базы; сценарий не подменяет базу.
function ScenariosPage() {
  const { api, forecast: c } = useAccount();
  const canWrite = useCompanyCanWrite();
  const f = c.forecast.data;
  return <section className="panel">
    <ForecastState />
    {!c.runId && !c.working && <Empty title="Нет выбранного расчёта"
      text="Рассчитайте прогноз или откройте сохранённый в разделе «Прогноз»." />}
    {f?.status === "succeeded" && <>
      <p className="mono">База: прогноз на {f.as_of} · {f.id}</p>
      {f.base_forecast_id
        ? <><p>Открыт сохранённый сценарий. Новый сценарий строится от базового прогноза.</p>
          <button type="button" onClick={() => c.open({ id: f.base_forecast_id!, as_of: f.as_of, job_id: null, error_code: null })}>
            Открыть исходный прогноз</button></>
        : canWrite ? <ScenarioPanel key={f.id} api={api} base={f} />
          : <Empty title="Сценарии запускает владелец компании" text="Сценарий создаёт отдельный расчёт на сервере." />}
    </>}
  </section>;
}

function PulsePage() {
  const { api, forecast: c } = useAccount();
  const f = c.forecast.data;
  return <section className="panel">
    <ForecastState />
    {!c.runId && !c.working && <Empty title="Нет выбранного расчёта"
      text="Пульс строится по сохранённому прогнозу. Рассчитайте его или откройте в разделе «Прогноз»." />}
    {f?.status === "succeeded" && <PulsePanel key={f.id} api={api} forecastId={f.id} />}
  </section>;
}

// Ассистент (PR №51) ещё не в main: показываем честное состояние без выдуманных ответов.
function AssistantPage() {
  return <Empty title="Ассистент появится после слияния PR №51"
    text="В этой сборке API ассистента нет. Остальные разделы работают без него." />;
}
