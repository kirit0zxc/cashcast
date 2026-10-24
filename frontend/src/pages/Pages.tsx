import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useAccount } from "../app/account-context";
import { ASSISTANT_ROUTE, ROUTES, navigate, type RoutePath } from "../app/router";
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
import { Tabs } from "../ui/Blank";
import { OverviewPage } from "./OverviewPage";

// Переключение раздела только меняет видимую страницу: данные и выбранный расчёт
// живут в AccountProvider, поэтому переход не отправляет POST и не создаёт job.
export function Pages({ route }: { route: RoutePath }) {
  switch (route) {
    case "/overview": return <OverviewPage />;
    case "/operations": return <Page route={route} lead="Только фактическое движение денег по выбранному счёту."
      action={<ImportButton />}><OperationsPage /></Page>;
    case "/import": return <Page route={route}
      lead="Сначала проверьте файл. Данные появятся в кабинете только после подтверждения."><ImportPage /></Page>;
    case "/payments": return <Page route={route}><PaymentsPage /></Page>;
    case "/reconciliation": return <Page route={route}><ReconciliationPage /></Page>;
    case "/forecast": return <Page route={route}><ForecastPanel /></Page>;
    case "/scenarios": return <Page route={route}><ScenariosPage /></Page>;
    case "/pulse": return <Page route={route}><PulsePage /></Page>;
    case "/assistant": return <Page route={route}><AssistantPage /></Page>;
  }
}

function Page({ route, lead, action, children }: {
  route: RoutePath; lead?: string; action?: ReactNode; children: ReactNode;
}) {
  const index = ROUTES.findIndex(r => r.path === route);
  const title = index >= 0 ? ROUTES[index].title : ASSISTANT_ROUTE.title;
  return <>
    <div className="page-title"><div>
      <span className="label">Раздел {String(index >= 0 ? index + 1 : 9).padStart(2, "0")}</span>
      <h1>{title}</h1>{lead && <p>{lead}</p>}</div>{action}</div>
    {children}
  </>;
}

function ImportButton() {
  return useCompanyCanWrite()
    ? <button type="button" className="ghost" onClick={() => navigate("/import")}>Импорт выписки</button> : null;
}

function OperationsPage() {
  const { api, companyId, accountId, categoryChanged } = useAccount();
  return <Transactions api={api} companyId={companyId} accountId={accountId} onChanged={categoryChanged} />;
}

function ImportPage() {
  const { api, companyId, accountId, statementCommitted, plansChanged } = useAccount();
  const canWrite = useCompanyCanWrite();
  const cache = useQueryClient();
  const [kind, setKind] = useState<"statement" | "obligations">("statement");
  if (!canWrite) return <Empty title="Импорт доступен владельцу компании" text="В режиме чтения можно смотреть операции и сохранённые расчёты." />;
  return <>
    <Tabs label="Вид данных" value={kind} onChange={setKind}
      items={[["statement", "Банковская выписка"], ["obligations", "Счета и обязательства"]]} />
    {kind === "statement"
      ? <StatementImport api={api} companyId={companyId} accountId={accountId} onCommit={statementCommitted} />
      : <ObligationImport api={api} companyId={companyId} accountId={accountId} onChanged={async () => {
        await cache.invalidateQueries({ queryKey: ["planned-events", companyId, accountId] });
        plansChanged();
      }} />}
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
