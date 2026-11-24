/**
 * Drawing tools rendered as a lightweight-charts series primitive (so they pan, zoom, rescale and appear in
 * screenshots with the chart). Anchors are stored as (chart time, price) and so survive timeframe changes; the host
 * supplies the time <-> logical-index mapping, which also lets anchors sit in the empty space right of the last bar.
 */
import type {
  IChartApi,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

export type DrawingType = "trend" | "ray" | "extended" | "hline" | "hray" | "vline" | "rect" | "fib" | "channel" | "measure" | "long" | "short" | "text";

export interface Anchor {
  t: number; // chart time, seconds (IST wall clock)
  p: number; // price
}

export interface Drawing {
  id: string;
  type: DrawingType;
  points: Anchor[];
  color: string;
  width: number;
  text?: string;
  locked?: boolean;
  hidden?: boolean;
}

export const TOOL_POINTS: Record<DrawingType, number> = {
  trend: 2, ray: 2, extended: 2, hline: 1, hray: 1, vline: 1, rect: 2, fib: 2, channel: 3, measure: 2, long: 2, short: 2, text: 1,
};

export const TOOL_LABEL: Record<DrawingType, string> = {
  trend: "Trend line", ray: "Ray", extended: "Extended line", hline: "Horizontal line", hray: "Horizontal ray", vline: "Vertical line",
  rect: "Rectangle", fib: "Fib retracement", channel: "Parallel channel", measure: "Price range", long: "Long position", short: "Short position",
  text: "Text",
};

export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618];
const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#4caf50", "#089981", "#00bcd4", "#787b86", "#2962ff"];

export interface Mapper {
  timeToLogical: (t: number) => number | null;
  logicalToTime: (l: number) => number | null;
}

interface Pt {
  x: number;
  y: number;
}

export interface Hit {
  id: string;
  handle: number; // -1 = body
}

const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);

function distToSegment(p: Pt, a: Pt, b: Pt, ray = 0): number {
  // ray: 0 segment, 1 extends past b, 2 extends both ways
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return dist(p, a);
  let u = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2;
  if (ray === 0) u = Math.max(0, Math.min(1, u));
  else if (ray === 1) u = Math.max(0, u);
  return dist(p, { x: a.x + u * dx, y: a.y + u * dy });
}

/** Extend the line a->b to the pane edges (x in [0, w]). */
function extendTo(a: Pt, b: Pt, w: number, both: boolean): [Pt, Pt] {
  if (a.x === b.x) return both ? [{ x: a.x, y: -1e5 }, { x: a.x, y: 1e5 }] : [a, { x: b.x, y: b.y > a.y ? 1e5 : -1e5 }];
  const m = (b.y - a.y) / (b.x - a.x);
  const toRight = b.x > a.x;
  const xEnd = toRight ? w : 0;
  const end = { x: xEnd, y: a.y + m * (xEnd - a.x) };
  if (!both) return [a, end];
  const xStart = toRight ? 0 : w;
  return [{ x: xStart, y: a.y + m * (xStart - a.x) }, end];
}

function fmt(p: number): string {
  return p.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function alpha(color: string, a: number): string {
  if (color.startsWith("#") && color.length === 7) {
    const n = parseInt(color.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  return color;
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, bg: string, fg = "#fff", align: CanvasTextAlign = "left") {
  ctx.font = "11px Inter, system-ui, sans-serif";
  const w = ctx.measureText(text).width + 8;
  const h = 16;
  const left = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
  ctx.fillStyle = bg;
  ctx.beginPath();
  ctx.roundRect(left, y - h / 2, w, h, 3);
  ctx.fill();
  ctx.fillStyle = fg;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(text, left + 4, y + 0.5);
}

export class DrawingLayer implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private drawings: Drawing[] = [];
  private preview: Drawing | null = null;
  private selected: string | null = null;
  private hovered: string | null = null;
  private mapper: Mapper | null = null;
  private barSeconds = 60;
  private textColor = "#d1d4dc";
  private readonly view: IPrimitivePaneView;

  constructor() {
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => {
        target.useMediaCoordinateSpace(({ context, mediaSize }) => this.drawAll(context, mediaSize.width, mediaSize.height));
      },
    };
    this.view = { renderer: () => renderer, zOrder: () => "top" };
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series as ISeriesApi<SeriesType>;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    const out: ISeriesPrimitiveAxisView[] = [];
    if (!this.series) return out;
    const all = this.preview ? [...this.drawings, this.preview] : this.drawings;
    for (const d of all) {
      if (d.hidden) continue;
      const show = d.type === "hline" || d.type === "hray" || d.id === this.selected || d === this.preview;
      if (!show) continue;
      const pts = d.type === "hline" || d.type === "hray" ? d.points.slice(0, 1) : d.points;
      for (const p of pts) {
        const y = this.series.priceToCoordinate(p.p);
        if (y == null) continue;
        out.push({ coordinate: () => y, text: () => fmt(p.p), textColor: () => "#fff", backColor: () => d.color, visible: () => true, tickVisible: () => true });
      }
    }
    return out;
  }

  updateAllViews(): void {
    // positions are computed at draw time
  }

  // ------------------------------------------------------------------ host API
  set(drawings: Drawing[], selected: string | null, preview: Drawing | null): void {
    this.drawings = drawings;
    this.selected = selected;
    this.preview = preview;
    this.requestUpdate?.();
  }

  setHovered(id: string | null): void {
    if (id !== this.hovered) {
      this.hovered = id;
      this.requestUpdate?.();
    }
  }

  setMapper(m: Mapper, barSeconds: number): void {
    this.mapper = m;
    this.barSeconds = barSeconds;
    this.requestUpdate?.();
  }

  setTextColor(c: string): void {
    this.textColor = c;
  }

  refresh(): void {
    this.requestUpdate?.();
  }

  /** Pane pixel -> anchor (time may lie right of the last bar). */
  toAnchor(x: number, y: number): Anchor | null {
    if (!this.chart || !this.series || !this.mapper) return null;
    const logical = this.chart.timeScale().coordinateToLogical(x);
    const price = this.series.coordinateToPrice(y);
    if (logical == null || price == null) return null;
    const t = this.mapper.logicalToTime(logical);
    return t == null ? null : { t, p: price };
  }

  toPoint(a: Anchor): Pt | null {
    if (!this.chart || !this.series || !this.mapper) return null;
    const l = this.mapper.timeToLogical(a.t);
    const y = this.series.priceToCoordinate(a.p);
    if (l == null || y == null) return null;
    const x = this.chart.timeScale().logicalToCoordinate(l as Logical);
    return x == null ? null : { x, y };
  }

  hit(x: number, y: number, width: number, tol = 6): Hit | null {
    const p = { x, y };
    for (let k = this.drawings.length - 1; k >= 0; k--) {
      const d = this.drawings[k]!;
      if (d.hidden) continue;
      const pts = d.points.map((a) => this.toPoint(a));
      if (pts.some((q) => q == null)) continue;
      const P = pts as Pt[];
      if (d.id === this.selected && !d.locked) {
        const handles = this.handles(d, P);
        for (let i = 0; i < handles.length; i++) if (dist(p, handles[i]!) <= tol + 2) return { id: d.id, handle: i };
      }
      if (this.bodyHit(d, P, p, width, tol)) return { id: d.id, handle: -1 };
    }
    return null;
  }

  /** Handle positions in the order of the points they move (long/short add a stop handle). */
  handles(d: Drawing, P: Pt[]): Pt[] {
    if (d.type === "long" || d.type === "short") {
      const stop = this.positionStop(d);
      const sy = this.series?.priceToCoordinate(stop) ?? P[0]!.y;
      return [P[0]!, { x: P[1]!.x, y: P[1]!.y }, { x: P[0]!.x, y: sy }];
    }
    if (d.type === "rect" || d.type === "measure") return [P[0]!, P[1]!, { x: P[0]!.x, y: P[1]!.y }, { x: P[1]!.x, y: P[0]!.y }];
    return P;
  }

  positionStop(d: Drawing): number {
    const entry = d.points[0]!.p;
    const target = d.points[1]!.p;
    return d.points[2]?.p ?? entry - (target - entry);
  }

  private bodyHit(d: Drawing, P: Pt[], p: Pt, w: number, tol: number): boolean {
    const [a, b] = P;
    switch (d.type) {
      case "hline":
        return Math.abs(p.y - a!.y) <= tol;
      case "hray":
        return Math.abs(p.y - a!.y) <= tol && p.x >= a!.x - tol;
      case "vline":
        return Math.abs(p.x - a!.x) <= tol;
      case "trend":
        return distToSegment(p, a!, b!) <= tol;
      case "ray":
        return distToSegment(p, a!, b!, 1) <= tol;
      case "extended":
        return distToSegment(p, a!, b!, 2) <= tol;
      case "text":
        return dist(p, a!) <= 30;
      case "channel": {
        const off = P[2] ? P[2].y - (a!.y + ((b!.y - a!.y) * (P[2].x - a!.x)) / (b!.x - a!.x || 1)) : 0;
        const a2 = { x: a!.x, y: a!.y + off };
        const b2 = { x: b!.x, y: b!.y + off };
        return distToSegment(p, a!, b!) <= tol || distToSegment(p, a2, b2) <= tol || this.inside(p, [a!, b!, b2, a2]);
      }
      case "long":
      case "short": {
        const sy = this.series?.priceToCoordinate(this.positionStop(d)) ?? a!.y;
        const x0 = Math.min(a!.x, b!.x);
        const x1 = Math.max(a!.x, b!.x);
        return p.x >= x0 - tol && p.x <= x1 + tol && p.y >= Math.min(b!.y, sy) - tol && p.y <= Math.max(b!.y, sy) + tol;
      }
      default: {
        // rect, fib, measure: inside the box (fib: near a level line)
        const x0 = Math.min(a!.x, b!.x);
        const x1 = d.type === "fib" ? w : Math.max(a!.x, b!.x);
        const y0 = Math.min(a!.y, b!.y);
        const y1 = Math.max(a!.y, b!.y);
        return p.x >= x0 - tol && p.x <= x1 + tol && p.y >= y0 - tol && p.y <= y1 + tol;
      }
    }
  }

  private inside(p: Pt, poly: Pt[]): boolean {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i]!;
      const b = poly[j]!;
      if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y || 1e-9) + a.x) inside = !inside;
    }
    return inside;
  }

  // ------------------------------------------------------------------ rendering
  private drawAll(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const all = this.preview ? [...this.drawings, this.preview] : this.drawings;
    for (const d of all) {
      if (d.hidden) continue;
      const pts = d.points.map((a) => this.toPoint(a));
      if (pts.length === 0 || pts.some((q) => q == null)) continue;
      ctx.save();
      const emph = d.id === this.selected || d.id === this.hovered || d === this.preview;
      ctx.lineWidth = d.width + (emph ? 0.5 : 0);
      ctx.strokeStyle = d.color;
      ctx.fillStyle = d.color;
      this.drawOne(ctx, d, pts as Pt[], w, h);
      if (d.id === this.selected || d === this.preview) {
        for (const hp of this.handles(d, pts as Pt[])) {
          ctx.beginPath();
          ctx.arc(hp.x, hp.y, 4.5, 0, Math.PI * 2);
          ctx.fillStyle = "#fff";
          ctx.fill();
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = d.color;
          ctx.stroke();
        }
      }
      ctx.restore();
    }
  }

  private line(ctx: CanvasRenderingContext2D, a: Pt, b: Pt) {
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  private drawOne(ctx: CanvasRenderingContext2D, d: Drawing, P: Pt[], w: number, h: number): void {
    const [a, b] = P;
    switch (d.type) {
      case "trend":
        this.line(ctx, a!, b!);
        break;
      case "ray": {
        const [s, e] = extendTo(a!, b!, w, false);
        this.line(ctx, s, e);
        break;
      }
      case "extended": {
        const [s, e] = extendTo(a!, b!, w, true);
        this.line(ctx, s, e);
        break;
      }
      case "hline":
        this.line(ctx, { x: 0, y: a!.y }, { x: w, y: a!.y });
        break;
      case "hray":
        this.line(ctx, a!, { x: w, y: a!.y });
        break;
      case "vline":
        this.line(ctx, { x: a!.x, y: 0 }, { x: a!.x, y: h });
        break;
      case "text": {
        ctx.font = "13px Inter, system-ui, sans-serif";
        ctx.textBaseline = "middle";
        ctx.fillStyle = d.color;
        ctx.fillText(d.text || "Text", a!.x, a!.y);
        break;
      }
      case "rect": {
        ctx.fillStyle = alpha(d.color, 0.14);
        ctx.fillRect(Math.min(a!.x, b!.x), Math.min(a!.y, b!.y), Math.abs(b!.x - a!.x), Math.abs(b!.y - a!.y));
        ctx.strokeRect(Math.min(a!.x, b!.x), Math.min(a!.y, b!.y), Math.abs(b!.x - a!.x), Math.abs(b!.y - a!.y));
        break;
      }
      case "channel": {
        const c = P[2] ?? b!;
        const slope = (b!.y - a!.y) / (b!.x - a!.x || 1);
        const off = c.y - (a!.y + slope * (c.x - a!.x));
        const a2 = { x: a!.x, y: a!.y + off };
        const b2 = { x: b!.x, y: b!.y + off };
        ctx.fillStyle = alpha(d.color, 0.1);
        ctx.beginPath();
        ctx.moveTo(a!.x, a!.y);
        ctx.lineTo(b!.x, b!.y);
        ctx.lineTo(b2.x, b2.y);
        ctx.lineTo(a2.x, a2.y);
        ctx.closePath();
        ctx.fill();
        this.line(ctx, a!, b!);
        this.line(ctx, a2, b2);
        ctx.setLineDash([4, 4]);
        this.line(ctx, { x: a!.x, y: (a!.y + a2.y) / 2 }, { x: b!.x, y: (b!.y + b2.y) / 2 });
        ctx.setLineDash([]);
        break;
      }
      case "fib": {
        const p0 = d.points[0]!.p;
        const p1 = d.points[1]!.p;
        const x0 = Math.min(a!.x, b!.x);
        let prevY: number | null = null;
        FIB_LEVELS.forEach((lv, i) => {
          const price = p1 + (p0 - p1) * lv; // 0 at the second point (the end of the move), 1 at the first
          const y = this.series?.priceToCoordinate(price);
          if (y == null) return;
          const col = FIB_COLORS[i % FIB_COLORS.length]!;
          if (prevY != null) {
            ctx.fillStyle = alpha(col, 0.08);
            ctx.fillRect(x0, Math.min(prevY, y), w - x0, Math.abs(y - prevY));
          }
          ctx.strokeStyle = col;
          ctx.lineWidth = 1;
          this.line(ctx, { x: x0, y }, { x: w, y });
          ctx.font = "11px Inter, system-ui, sans-serif";
          ctx.fillStyle = col;
          ctx.textBaseline = "bottom";
          ctx.fillText(`${lv} (${fmt(price)})`, x0 + 4, y - 2);
          prevY = y;
        });
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = alpha(d.color, 0.6);
        this.line(ctx, a!, b!);
        ctx.setLineDash([]);
        break;
      }
      case "measure": {
        const up = d.points[1]!.p >= d.points[0]!.p;
        const col = up ? "#2962ff" : "#f23645";
        ctx.fillStyle = alpha(col, 0.15);
        ctx.fillRect(Math.min(a!.x, b!.x), Math.min(a!.y, b!.y), Math.abs(b!.x - a!.x), Math.abs(b!.y - a!.y));
        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        const midX = (a!.x + b!.x) / 2;
        this.line(ctx, { x: midX, y: a!.y }, { x: midX, y: b!.y });
        const dp = d.points[1]!.p - d.points[0]!.p;
        const pct = (dp / d.points[0]!.p) * 100;
        const la = this.mapper?.timeToLogical(d.points[0]!.t);
        const lb = this.mapper?.timeToLogical(d.points[1]!.t);
        const bars = la != null && lb != null ? Math.round(Math.abs(lb - la)) : 0;
        const txt = `${dp >= 0 ? "+" : ""}${fmt(dp)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%) · ${bars} bars`;
        label(ctx, txt, midX, up ? Math.min(a!.y, b!.y) - 12 : Math.max(a!.y, b!.y) + 12, col, "#fff", "center");
        break;
      }
      case "long":
      case "short": {
        const entry = d.points[0]!.p;
        const target = d.points[1]!.p;
        const stop = this.positionStop(d);
        const ty = b!.y;
        const sy = this.series?.priceToCoordinate(stop) ?? a!.y;
        const x0 = Math.min(a!.x, b!.x);
        const x1 = Math.max(a!.x, b!.x);
        ctx.fillStyle = "rgba(8,153,129,0.18)";
        ctx.fillRect(x0, Math.min(a!.y, ty), x1 - x0, Math.abs(ty - a!.y));
        ctx.fillStyle = "rgba(242,54,69,0.18)";
        ctx.fillRect(x0, Math.min(a!.y, sy), x1 - x0, Math.abs(sy - a!.y));
        ctx.strokeStyle = "#787b86";
        ctx.lineWidth = 1;
        this.line(ctx, { x: x0, y: a!.y }, { x: x1, y: a!.y });
        const reward = Math.abs(target - entry);
        const risk = Math.abs(entry - stop);
        const rr = risk > 0 ? reward / risk : 0;
        const pctT = ((target - entry) / entry) * 100;
        const pctS = ((stop - entry) / entry) * 100;
        label(ctx, `Target ${fmt(target)} (${pctT >= 0 ? "+" : ""}${pctT.toFixed(2)}%)`, (x0 + x1) / 2, ty + (ty < a!.y ? -10 : 10), "#089981", "#fff", "center");
        label(ctx, `Stop ${fmt(stop)} (${pctS >= 0 ? "+" : ""}${pctS.toFixed(2)}%)`, (x0 + x1) / 2, sy + (sy > a!.y ? 10 : -10), "#f23645", "#fff", "center");
        label(ctx, `${d.type === "long" ? "Long" : "Short"} ${fmt(entry)} · R:R ${rr.toFixed(2)}`, (x0 + x1) / 2, a!.y, "#2a2e39", "#fff", "center");
        break;
      }
    }
    if (d.text && d.type !== "text" && P[0]) {
      ctx.font = "11px Inter, system-ui, sans-serif";
      ctx.fillStyle = this.textColor;
      ctx.fillText(d.text, P[0].x + 6, P[0].y - 6);
    }
  }
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
}
