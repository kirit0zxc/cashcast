import type { Point } from "../shared/api";

const W = 760, H = 280;
const PAD = { l: 76, r: 16, t: 16, b: 28 };

// Короткие подписи оси: точные суммы — в таблице прогноза.
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

// График бланка: медиана чернилами, коридор точечным растром, перекрестие на минимуме.
export function SpecChart({ points, label }: { points: Point[]; label: string }) {
  if (points.length < 2) return null;
  const values = points.flatMap(p => [p.balance_p10_minor, p.balance_p90_minor, p.balance_p50_minor]);
  let lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || Math.max(1, Math.abs(hi) * 0.1) || 100;
  lo -= span * 0.12; hi += span * 0.12;
  const x = (i: number) => PAD.l + (i / (points.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.balance_p50_minor).toFixed(1)}`).join("");
  const band = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.balance_p90_minor).toFixed(1)}`).join("")
    + [...points].reverse().map((p, j) => `L${x(points.length - 1 - j).toFixed(1)},${y(p.balance_p10_minor).toFixed(1)}`).join("") + "Z";
  const step = niceStep((hi - lo) / 4);
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  const xt = [0, 7, 14, 21, points.length - 1].filter((i, k, all) => i < points.length && all.indexOf(i) === k);
  const minIdx = points.reduce((m, p, i) => p.balance_p50_minor < points[m].balance_p50_minor ? i : m, 0);
  const min = points[minIdx];
  const zero = lo < 0 && hi > 0 ? y(0) : null;
  const labelLeft = x(minIdx) > W - 150;
  return <svg className="spec" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={label}>
    <defs><pattern id="spec-dot" width="5" height="5" patternUnits="userSpaceOnUse">
      <circle cx="2.5" cy="2.5" r="1.05" fill="var(--ink)" /></pattern></defs>
    {ticks.map(v => <g key={v}>
      <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="var(--ink)" strokeOpacity=".15" />
      <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end">{compactRub(v)}</text>
    </g>)}
    {zero !== null && <line x1={PAD.l} x2={W - PAD.r} y1={zero} y2={zero} stroke="var(--coral)" strokeDasharray="4 3" />}
    {bandAvailable(points) && <path d={band} fill="url(#spec-dot)" opacity=".55" />}
    <path d={line} fill="none" stroke="var(--ink)" strokeWidth="2.4" />
    {xt.map(i => <text key={i} x={x(i)} y={H - 6} textAnchor="middle">{dd(points[i].point_date)}</text>)}
    <g transform={`translate(${x(minIdx)},${y(min.balance_p50_minor)})`}>
      <circle r="9" fill="none" stroke="var(--ink)" />
      <path d="M-15 0h8M7 0h8M0-15v8M0 7v8" stroke="var(--ink)" />
    </g>
    <text x={x(minIdx) + (labelLeft ? -14 : 14)} y={y(min.balance_p50_minor) - 12} textAnchor={labelLeft ? "end" : "start"}
      style={{ fill: "var(--ink)", fontWeight: 700 }}>MIN {compactRub(min.balance_p50_minor)}</text>
  </svg>;
}
