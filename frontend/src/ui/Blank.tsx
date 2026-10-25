import type { ReactNode } from "react";

// Мелкие элементы бланка варианта A: строки с отточием, шаги, вкладки.

export function Leaders({ rows, testId }: { rows: [ReactNode, ReactNode][]; testId?: string }) {
  return <dl className="leaders" data-testid={testId}>
    {rows.map(([term, value], i) => <div key={i}><dt>{term}</dt><i aria-hidden="true" /><dd>{value}</dd></div>)}
  </dl>;
}

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return <ol className="stepper" aria-label="Шаги">
    {steps.map((step, i) => <li key={step} className={i < current ? "is-done" : i === current ? "is-on" : ""}
      aria-current={i === current ? "step" : undefined}>
      <span className="mono">{String(i + 1).padStart(2, "0")}</span>{step}</li>)}
  </ol>;
}

export function Tabs<T extends string>({ label, items, value, onChange }: {
  label: string; items: [T, string][]; value: T; onChange: (value: T) => void;
}) {
  return <div className="tabs" role="tablist" aria-label={label}>
    {items.map(([id, title]) => <button key={id} type="button" role="tab" aria-selected={value === id}
      className={value === id ? "" : "ghost"} onClick={() => onChange(id)}>{title}</button>)}
  </div>;
}

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
/** 2026-10-24 → 24.10.2026 */
export const dmy = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
/** 2026-10-24 → 24 окт */
export const dayMonth = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
