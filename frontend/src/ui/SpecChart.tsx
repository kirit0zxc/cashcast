import { useState, type PointerEvent } from "react";
import { money, type Point } from "../shared/api";

const W = 760, H = 280;
const PAD = { l: 76, r: 16, t: 22, b: 28 };

// Короткие подписи оси: точные суммы — в подсказке и таблице.
export function compactRub(minor: number): string {
  const rub = minor / 100;
  if (Math.abs(rub) >= 1e6) return `${(rub / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн`;
  if (Math.abs(rub) >= 1e3) return `${Math.round(rub / 1e3)} тыс`;
  return `${Math.round(rub)}`;
}

function niceStep(raw: number) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * p;
}

const dd = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

// Коридор p10–p90 может схлопнуться при слабых данных — тогда честно пишем «недоступен».
export const bandAvailable = (points: Point[]) => points.some(p => p.balance_p90_minor - p.balance_p10_minor > 100);

export interface Series {
  name: string;
  values: (number | null)[];
  /** ink — основная линия, dash — пунктир, thin — тонкая, coral — внимание. */
  style: "ink" | "dash" | "thin" | "coral";
}

const STROKE: Record<Series["style"], { stroke: string; width: number; dash?: string }> = {
  ink: { stroke: "var(--ink)", width: 2.4 },
  dash: { stroke: "var(--ink)", width: 1.6, dash: "6 4" },
  thin: { stroke: "var(--ink-2)", width: 1.2 },
  coral: { stroke: "var(--coral)", width: 2, dash: "2 3" },
};

// Линейный график бланка: линии чернилами, коридор точечным растром, перекрестие
// на минимуме первой линии, подсказка с точными суммами при наведении.
export function SpecLines({ dates, series, band, label, markMin = true }: {
  dates: string[]; series: Series[]; band?: { low: number[]; high: number[] } | null; label: string; markMin?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (dates.length < 2 || !series.length) return null;
  const values = [...series.flatMap(s => s.values), ...(band ? [...band.low, ...band.high] : [])]
    .filter((v): v is number => v !== null);
  let lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || Math.max(100, Math.abs(hi) * 0.1);
  lo -= span * 0.12; hi += span * 0.12;
  const x = (i: number) => PAD.l + (i / (dates.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const path = (vals: (number | null)[]) => vals.map((v, i) => v === null ? "" :
    `${i && vals[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const step = niceStep((hi - lo) / 4);
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  const xt = [0, 7, 14, 21, dates.length - 1].filter((i, k, all) => i < dates.length && all.indexOf(i) === k);
  const main = series[0].values;
  const minIdx = main.reduce<number>((m, v, i) => v !== null && (main[m] === null || v < main[m]!) ? i : m, 0);
  const min = main[minIdx];
  const zero = lo < 0 && hi > 0 ? y(0) : null;
  const labelLeft = x(minIdx) > W - 150;
  const bandPath = band ? band.high.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")
    + [...band.low].reverse().map((v, j) => `L${x(dates.length - 1 - j).toFixed(1)},${y(v).toFixed(1)}`).join("") + "Z" : "";

  function move(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const vx = ((event.clientX - box.left) / box.width) * W;
    const i = Math.round(((vx - PAD.l) / (W - PAD.l - PAD.r)) * (dates.length - 1));
    setHover(i >= 0 && i < dates.length ? i : null);
  }
  const tipX = hover !== null ? Math.min(Math.max(x(hover) + 10, PAD.l), W - 190) : 0;

  return <svg className="spec" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={label}
    onPointerMove={move} onPointerLeave={() => setHover(null)}>
    <defs><pattern id="spec-dot" width="5" height="5" patternUnits="userSpaceOnUse">
      <circle cx="2.5" cy="2.5" r="1.05" fill="var(--ink)" /></pattern></defs>
    {ticks.map(v => <g key={v}>
      <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="var(--ink)" strokeOpacity=".15" />
      <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end">{compactRub(v)}</text>
    </g>)}
    {zero !== null && <line x1={PAD.l} x2={W - PAD.r} y1={zero} y2={zero} stroke="var(--coral)" strokeDasharray="4 3" />}
    {band && <path d={bandPath} fill="url(#spec-dot)" opacity=".55" />}
    {[...series].reverse().map(s => <path key={s.name} d={path(s.values)} fill="none" stroke={STROKE[s.style].stroke}
      strokeWidth={STROKE[s.style].width} strokeDasharray={STROKE[s.style].dash} />)}
    {xt.map(i => <text key={i} x={x(i)} y={H - 6} textAnchor="middle">{dd(dates[i])}</text>)}
    {markMin && min !== null && <>
      <g transform={`translate(${x(minIdx)},${y(min)})`}>
        <circle r="9" fill="none" stroke="var(--ink)" />
        <path d="M-15 0h8M7 0h8M0-15v8M0 7v8" stroke="var(--ink)" />
      </g>
      <text x={x(minIdx) + (labelLeft ? -14 : 14)} y={y(min) - 12} textAnchor={labelLeft ? "end" : "start"}
        style={{ fill: "var(--ink)", fontWeight: 700 }}>MIN {compactRub(min)}</text>
    </>}
    {hover !== null && <g pointerEvents="none">
      <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} stroke="var(--ink)" strokeDasharray="2 2" />
      <rect x={tipX} y={2} width={180} height={16 + series.length * 15} fill="var(--paper)" stroke="var(--ink)" />
      <text x={tipX + 8} y={15} style={{ fill: "var(--ink)", fontWeight: 700 }}>{dd(dates[hover])}.{dates[hover].slice(0, 4)}</text>
      {series.map((s, k) => <text key={s.name} x={tipX + 8} y={30 + k * 15}>
        {s.name}: {s.values[hover] === null ? "—" : money(s.values[hover]!)}</text>)}
    </g>}
  </svg>;
}

// Прогноз остатка: медиана и коридор p10–p90 из сохранённого расчёта.
export function SpecChart({ points, label }: { points: Point[]; label: string }) {
  return <SpecLines label={label} dates={points.map(p => p.point_date)}
    series={[{ name: "медиана", values: points.map(p => p.balance_p50_minor), style: "ink" }]}
    band={bandAvailable(points) ? { low: points.map(p => p.balance_p10_minor), high: points.map(p => p.balance_p90_minor) } : null} />;
}
