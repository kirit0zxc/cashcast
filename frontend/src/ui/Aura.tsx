import { useEffect, useRef } from "react";

type Rgb = [number, number, number];
interface Blob { x: number; y: number; r: number; c: Rgb; a?: number }

const IRIS: Record<string, Rgb> = {
  pink: [255, 120, 170], coral: [255, 110, 80], amber: [255, 200, 90], lilac: [170, 140, 255],
  blue: [90, 120, 255], cyan: [120, 220, 255], violet: [120, 70, 220], grey: [170, 169, 164],
};

// Статус задаёт палитру: спокойно — холодные, внимание — тёплые, риск — коралл; нет данных — серый.
const PALETTES: Record<string, Blob[]> = {
  ok: [{ x: .4, y: .5, r: .35, c: IRIS.blue }, { x: .65, y: .4, r: .3, c: IRIS.cyan }, { x: .55, y: .7, r: .28, c: IRIS.lilac }],
  watch: [{ x: .38, y: .55, r: .34, c: IRIS.pink }, { x: .62, y: .38, r: .3, c: IRIS.amber }, { x: .58, y: .72, r: .3, c: IRIS.lilac }],
  risk: [{ x: .45, y: .5, r: .36, c: IRIS.coral }, { x: .6, y: .35, r: .28, c: IRIS.pink }, { x: .5, y: .75, r: .26, c: IRIS.violet }],
  unknown: [{ x: .45, y: .5, r: .36, c: IRIS.grey }, { x: .62, y: .4, r: .26, c: IRIS.grey, a: .6 }],
  assistant: [{ x: .5, y: .45, r: .45, c: IRIS.pink }, { x: .6, y: .65, r: .35, c: IRIS.lilac }, { x: .35, y: .6, r: .3, c: IRIS.amber }],
};

// Растровая аура: мягкие радужные сферы печатаются точками разного размера.
function draw(canvas: HTMLCanvasElement, blobs: Blob[], cell: number) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  const size = Math.max(w, h);
  for (let py = cell / 2; py < h; py += cell) {
    for (let px = cell / 2; px < w; px += cell) {
      let a = 0, r = 0, g = 0, b = 0;
      for (const bl of blobs) {
        const dx = (px - bl.x * w) / (bl.r * size), dy = (py - bl.y * h) / (bl.r * size);
        const k = Math.exp(-(dx * dx + dy * dy) * 2.2) * (bl.a ?? 1);
        a += k; r += bl.c[0] * k; g += bl.c[1] * k; b += bl.c[2] * k;
      }
      if (a < 0.04) continue;
      ctx.fillStyle = `rgb(${(r / a) | 0},${(g / a) | 0},${(b / a) | 0})`;
      ctx.beginPath(); ctx.arc(px, py, cell * 0.62 * Math.sqrt(Math.min(1, a)), 0, Math.PI * 2); ctx.fill();
    }
  }
}

export function Aura({ tone, cell = 7, className }: { tone: string; cell?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const blobs = PALETTES[tone] ?? PALETTES.unknown;
    const redraw = () => draw(canvas, blobs, cell);
    redraw();
    const observer = new ResizeObserver(redraw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [tone, cell]);
  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
