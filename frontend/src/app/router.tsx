import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from "react";

// Pathname-маршруты без зависимостей: nginx отдаёт index.html на любой путь,
// Back/Forward и прямой адрес открывают нужный раздел. Переход не трогает данные.
export const ROUTES = [
  { path: "/overview", title: "Обзор" },
  { path: "/operations", title: "Операции" },
  { path: "/import", title: "Импорт данных" },
  { path: "/payments", title: "Плановые платежи" },
  { path: "/reconciliation", title: "Сверка оплат" },
  { path: "/forecast", title: "Прогноз" },
  { path: "/scenarios", title: "Сценарии" },
  { path: "/pulse", title: "Финансовый пульс" },
  { path: "/evaluation", title: "Проверка качества" },
] as const;
export const ASSISTANT_ROUTE = { path: "/assistant", title: "ИИ-ассистент" } as const;
export type RoutePath = (typeof ROUTES)[number]["path"] | typeof ASSISTANT_ROUTE.path;

const known = new Set<string>([...ROUTES.map(r => r.path), ASSISTANT_ROUTE.path]);
const DEFAULT: RoutePath = "/overview";

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  return () => window.removeEventListener("popstate", notify);
}
function current(): RoutePath {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  return (known.has(path) ? path : DEFAULT) as RoutePath;
}

export function useRoute(): RoutePath {
  return useSyncExternalStore(subscribe, current);
}

export function navigate(path: RoutePath) {
  if (window.location.pathname === path) return;
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

// Неизвестный путь (включая «/») заменяется на обзор без лишней записи в истории.
export function normalizeLocation() {
  const path = current();
  if (window.location.pathname !== path) window.history.replaceState(null, "", path);
}

export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: RoutePath }) {
  function click(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  }
  return <a href={to} onClick={click} {...rest} />;
}
