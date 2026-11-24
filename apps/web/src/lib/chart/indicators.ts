/**
 * Technical indicator library for the Charts terminal.
 *
 * Conventions follow the common charting-platform definitions (Pine Script `ta.*`): EMA and Wilder's RMA are
 * seeded with a simple average of the first `n` values, standard deviation is the population form, RSI/ATR/ADX use
 * Wilder smoothing, CCI uses the mean absolute deviation of the typical price. Outputs are arrays aligned with the
 * input bars; `null` marks the warm-up period (never a fabricated value).
 */

export type Num = number | null;
export type Out = Num[];

export interface BarsInput {
  t: number[]; // chart time (seconds, IST wall clock)
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
  /** seconds per bar (approximate for D/W/M) */
  barSeconds: number;
  /** "min" | "D" | "W" | "M" */
  unit: string;
}

export type Source = "close" | "open" | "high" | "low" | "hl2" | "hlc3" | "ohlc4";
export const SOURCES: Source[] = ["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"];

export function source(b: BarsInput, s: Source = "close"): number[] {
  const n = b.c.length;
  const out = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    switch (s) {
      case "open":
        out[i] = b.o[i]!;
        break;
      case "high":
        out[i] = b.h[i]!;
        break;
      case "low":
        out[i] = b.l[i]!;
        break;
      case "hl2":
        out[i] = (b.h[i]! + b.l[i]!) / 2;
        break;
      case "hlc3":
        out[i] = (b.h[i]! + b.l[i]! + b.c[i]!) / 3;
        break;
      case "ohlc4":
        out[i] = (b.o[i]! + b.h[i]! + b.l[i]! + b.c[i]!) / 4;
        break;
      default:
        out[i] = b.c[i]!;
    }
  }
  return out;
}

// ------------------------------------------------------------------------------------------------ primitives
const nulls = (n: number): Out => new Array<Num>(n).fill(null);

export function sma(x: Out, n: number): Out {
  const out = nulls(x.length);
  let sum = 0;
  let count = 0;
  for (let i = 0; i < x.length; i++) {
    const v = x[i];
    if (v == null) {
      sum = 0;
      count = 0;
      continue;
    }
    sum += v;
    count++;
    if (count > n) {
      sum -= x[i - n] as number;
      count = n;
    }
    if (count === n) out[i] = sum / n;
  }
  return out;
}

/** Exponential average with smoothing `alpha`, seeded with the SMA of the first `n` valid values. */
function expAvg(x: Out, n: number, alpha: number): Out {
  const out = nulls(x.length);
  let prev: number | null = null;
  let seed = 0;
  let seen = 0;
  for (let i = 0; i < x.length; i++) {
    const v = x[i];
    if (v == null) continue;
    if (prev == null) {
      seed += v;
      seen++;
      if (seen === n) {
        prev = seed / n;
        out[i] = prev;
      }
      continue;
    }
    prev = alpha * v + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

export const ema = (x: Out, n: number): Out => expAvg(x, n, 2 / (n + 1));
/** Wilder's moving average (RMA). */
export const rma = (x: Out, n: number): Out => expAvg(x, n, 1 / n);

export function wma(x: Out, n: number): Out {
  const out = nulls(x.length);
  const denom = (n * (n + 1)) / 2;
  for (let i = n - 1; i < x.length; i++) {
    let s = 0;
    let ok = true;
    for (let k = 0; k < n; k++) {
      const v = x[i - k];
      if (v == null) {
        ok = false;
        break;
      }
      s += v * (n - k);
    }
    if (ok) out[i] = s / denom;
  }
  return out;
}

/** Population standard deviation over `n`. */
export function stdev(x: Out, n: number): Out {
  const out = nulls(x.length);
  const m = sma(x, n);
  for (let i = n - 1; i < x.length; i++) {
    const mu = m[i];
    if (mu == null) continue;
    let s = 0;
    for (let k = 0; k < n; k++) {
      const d = (x[i - k] as number) - mu;
      s += d * d;
    }
    out[i] = Math.sqrt(s / n);
  }
  return out;
}

export function highest(x: Out, n: number): Out {
  const out = nulls(x.length);
  for (let i = n - 1; i < x.length; i++) {
    let m = -Infinity;
    for (let k = 0; k < n; k++) m = Math.max(m, x[i - k] ?? -Infinity);
    out[i] = Number.isFinite(m) ? m : null;
  }
  return out;
}

export function lowest(x: Out, n: number): Out {
  const out = nulls(x.length);
  for (let i = n - 1; i < x.length; i++) {
    let m = Infinity;
    for (let k = 0; k < n; k++) m = Math.min(m, x[i - k] ?? Infinity);
    out[i] = Number.isFinite(m) ? m : null;
  }
  return out;
}

export function trueRange(b: BarsInput): Out {
  return b.c.map((_, i) => (i === 0 ? b.h[0]! - b.l[0]! : Math.max(b.h[i]! - b.l[i]!, Math.abs(b.h[i]! - b.c[i - 1]!), Math.abs(b.l[i]! - b.c[i - 1]!))));
}

export const atr = (b: BarsInput, n: number): Out => rma(trueRange(b), n);

const sub = (a: Out, b: Out): Out => a.map((v, i) => (v == null || b[i] == null ? null : v - (b[i] as number)));
const change = (x: Out, n = 1): Out => x.map((v, i) => (i < n || v == null || x[i - n] == null ? null : v - (x[i - n] as number)));

export function rsiOf(x: Out, n: number): Out {
  const up: Out = x.map((v, i) => (i === 0 || v == null || x[i - 1] == null ? null : Math.max(v - (x[i - 1] as number), 0)));
  const dn: Out = x.map((v, i) => (i === 0 || v == null || x[i - 1] == null ? null : Math.max((x[i - 1] as number) - v, 0)));
  const au = rma(up, n);
  const ad = rma(dn, n);
  return au.map((u, i) => {
    const d = ad[i];
    if (u == null || d == null) return null;
    if (d === 0) return u === 0 ? 50 : 100;
    return 100 - 100 / (1 + u / d);
  });
}

// ------------------------------------------------------------------------------------------------ definitions
export interface ParamDef {
  key: string;
  label: string;
  type: "int" | "float" | "source";
  default: number | Source;
  min?: number;
  max?: number;
  step?: number;
}

export interface PlotDef {
  key: string;
  title: string;
  kind: "line" | "histogram" | "step" | "dots";
  color: string;
  width?: number;
  dashed?: boolean;
}

export type Params = Record<string, number | string>;

export interface IndicatorDef {
  id: string;
  name: string;
  short: string;
  category: "Moving averages" | "Bands & channels" | "Trend" | "Momentum" | "Volatility" | "Volume";
  overlay: boolean;
  description: string;
  params: ParamDef[];
  plots: PlotDef[];
  levels?: { value: number; color?: string }[];
  /** fixed autoscale range for bounded oscillators */
  range?: [number, number];
  compute: (b: BarsInput, p: Params) => Record<string, Out>;
  /** per-bar colour for histogram plots */
  barColor?: (key: string, i: number, out: Record<string, Out>, b: BarsInput) => string | undefined;
}

const UP = "#26a69a";
const DOWN = "#ef5350";
const C = { blue: "#2962ff", orange: "#ff6d00", purple: "#7e57c2", teal: "#00897b", red: "#f23645", green: "#089981", gray: "#787b86", yellow: "#f7c948", pink: "#e91e63", cyan: "#00bcd4" };

const len = (d = 14, min = 1, max = 500): ParamDef => ({ key: "length", label: "Length", type: "int", default: d, min, max });
const src = (d: Source = "close"): ParamDef => ({ key: "source", label: "Source", type: "source", default: d });
const P = (p: Params, k: string, d: number) => {
  const v = Number(p[k]);
  return Number.isFinite(v) && v > 0 ? v : d;
};
const S = (p: Params, d: Source = "close") => (SOURCES.includes(p.source as Source) ? (p.source as Source) : d);

function maDef(id: string, name: string, color: string, fn: (x: Out, n: number, b: BarsInput) => Out, description: string, d = 20): IndicatorDef {
  return {
    id, name, short: id, category: "Moving averages", overlay: true, description,
    params: [len(d), src()],
    plots: [{ key: "ma", title: id, kind: "line", color, width: 2 }],
    compute: (b, p) => ({ ma: fn(source(b, S(p)), Math.round(P(p, "length", d)), b) }),
  };
}

function hma(x: Out, n: number): Out {
  const half = wma(x, Math.max(1, Math.floor(n / 2)));
  const full = wma(x, n);
  const diff = half.map((h, i) => (h == null || full[i] == null ? null : 2 * h - (full[i] as number)));
  return wma(diff, Math.max(1, Math.round(Math.sqrt(n))));
}

function vwma(x: Out, n: number, b: BarsInput): Out {
  const pv = sma(x.map((v, i) => (v == null ? null : v * b.v[i]!)), n);
  const vv = sma(b.v, n);
  return pv.map((a, i) => (a == null || !vv[i] ? null : a / (vv[i] as number)));
}

/** Period key used to reset session-anchored indicators (VWAP) and to group pivots. */
function periodKey(t: number, unit: "day" | "week" | "month" | "year"): number {
  const d = new Date(t * 1000); // chart times are IST wall-clock expressed as UTC
  if (unit === "day") return Math.floor(t / 86400);
  if (unit === "month") return d.getUTCFullYear() * 12 + d.getUTCMonth();
  if (unit === "year") return d.getUTCFullYear();
  const day = Math.floor(t / 86400);
  return Math.floor((day + 3) / 7); // weeks starting Monday (1970-01-01 was a Thursday)
}

export const INDICATORS: IndicatorDef[] = [
  maDef("SMA", "Moving Average (Simple)", C.blue, (x, n) => sma(x, n), "Arithmetic mean of the last n prices."),
  maDef("EMA", "Moving Average (Exponential)", C.orange, (x, n) => ema(x, n), "Weights recent prices more; reacts faster than the SMA."),
  maDef("WMA", "Moving Average (Weighted)", C.purple, (x, n) => wma(x, n), "Linearly weighted average (newest bar weighs n)."),
  maDef("HMA", "Hull Moving Average", C.teal, (x, n) => hma(x, n), "Low-lag average: WMA(2·WMA(n/2) − WMA(n), √n).", 9),
  maDef("VWMA", "Volume-Weighted Moving Average", C.pink, (x, n, b) => vwma(x, n, b), "Average weighted by each bar's volume."),
  maDef("DEMA", "Double EMA", C.cyan, (x, n) => sub(ema(x, n).map((v) => (v == null ? null : 2 * v)), ema(ema(x, n), n)), "2·EMA − EMA(EMA): less lag than an EMA."),
  maDef("TEMA", "Triple EMA", C.yellow, (x, n) => {
    const e1 = ema(x, n);
    const e2 = ema(e1, n);
    const e3 = ema(e2, n);
    return e1.map((a, i) => (a == null || e2[i] == null || e3[i] == null ? null : 3 * a - 3 * (e2[i] as number) + (e3[i] as number)));
  }, "3·EMA − 3·EMA² + EMA³."),
  {
    id: "VWAP", name: "VWAP (session)", short: "VWAP", category: "Moving averages", overlay: true,
    description: "Volume-weighted average price of the typical price (hlc3), reset at every session (each trading day).",
    params: [], plots: [{ key: "vwap", title: "VWAP", kind: "line", color: C.blue, width: 2 }],
    compute: (b) => {
      const tp = source(b, "hlc3");
      const out = nulls(tp.length);
      let key = -1;
      let pv = 0;
      let vol = 0;
      for (let i = 0; i < tp.length; i++) {
        const k = b.unit === "min" ? periodKey(b.t[i]!, "day") : i; // daily+ bars: each bar is its own session
        if (k !== key) {
          key = k;
          pv = 0;
          vol = 0;
        }
        pv += tp[i]! * b.v[i]!;
        vol += b.v[i]!;
        out[i] = vol > 0 ? pv / vol : tp[i]!;
      }
      return { vwap: out };
    },
  },
  {
    id: "BB", name: "Bollinger Bands", short: "BB", category: "Bands & channels", overlay: true,
    description: "SMA ± k standard deviations.",
    params: [len(20), { key: "mult", label: "StdDev", type: "float", default: 2, min: 0.1, max: 10, step: 0.1 }, src()],
    plots: [
      { key: "basis", title: "Basis", kind: "line", color: C.orange, width: 1 },
      { key: "upper", title: "Upper", kind: "line", color: C.blue, width: 1 },
      { key: "lower", title: "Lower", kind: "line", color: C.blue, width: 1 },
    ],
    compute: (b, p) => {
      const x = source(b, S(p));
      const n = Math.round(P(p, "length", 20));
      const k = P(p, "mult", 2);
      const basis = sma(x, n);
      const sd = stdev(x, n);
      return {
        basis,
        upper: basis.map((m, i) => (m == null || sd[i] == null ? null : m + k * (sd[i] as number))),
        lower: basis.map((m, i) => (m == null || sd[i] == null ? null : m - k * (sd[i] as number))),
      };
    },
  },
  {
    id: "KC", name: "Keltner Channels", short: "KC", category: "Bands & channels", overlay: true,
    description: "EMA ± multiple of the ATR.",
    params: [len(20), { key: "mult", label: "Multiplier", type: "float", default: 2, min: 0.1, max: 10, step: 0.1 },
      { key: "atr", label: "ATR length", type: "int", default: 10, min: 1, max: 200 }],
    plots: [
      { key: "basis", title: "Basis", kind: "line", color: C.blue, width: 1 },
      { key: "upper", title: "Upper", kind: "line", color: C.teal, width: 1 },
      { key: "lower", title: "Lower", kind: "line", color: C.teal, width: 1 },
    ],
    compute: (b, p) => {
      const basis = ema(b.c, Math.round(P(p, "length", 20)));
      const r = atr(b, Math.round(P(p, "atr", 10)));
      const k = P(p, "mult", 2);
      return {
        basis,
        upper: basis.map((m, i) => (m == null || r[i] == null ? null : m + k * (r[i] as number))),
        lower: basis.map((m, i) => (m == null || r[i] == null ? null : m - k * (r[i] as number))),
      };
    },
  },
  {
    id: "DC", name: "Donchian Channels", short: "DC", category: "Bands & channels", overlay: true,
    description: "Highest high and lowest low over n bars, and their midpoint.",
    params: [len(20)],
    plots: [
      { key: "upper", title: "Upper", kind: "line", color: C.blue, width: 1 },
      { key: "basis", title: "Basis", kind: "line", color: C.orange, width: 1 },
      { key: "lower", title: "Lower", kind: "line", color: C.blue, width: 1 },
    ],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 20));
      const up = highest(b.h, n);
      const lo = lowest(b.l, n);
      return { upper: up, lower: lo, basis: up.map((u, i) => (u == null || lo[i] == null ? null : (u + (lo[i] as number)) / 2)) };
    },
  },
  {
    id: "ENV", name: "Envelopes", short: "ENV", category: "Bands & channels", overlay: true,
    description: "SMA shifted up and down by a fixed percentage.",
    params: [len(20), { key: "percent", label: "Percent", type: "float", default: 10, min: 0.1, max: 50, step: 0.1 }, src()],
    plots: [
      { key: "basis", title: "Basis", kind: "line", color: C.orange, width: 1 },
      { key: "upper", title: "Upper", kind: "line", color: C.blue, width: 1 },
      { key: "lower", title: "Lower", kind: "line", color: C.blue, width: 1 },
    ],
    compute: (b, p) => {
      const basis = sma(source(b, S(p)), Math.round(P(p, "length", 20)));
      const k = P(p, "percent", 10) / 100;
      return { basis, upper: basis.map((m) => (m == null ? null : m * (1 + k))), lower: basis.map((m) => (m == null ? null : m * (1 - k))) };
    },
  },
  {
    id: "ST", name: "Supertrend", short: "Supertrend", category: "Trend", overlay: true,
    description: "ATR trailing band that flips with the trend (green below price in uptrends, red above in downtrends).",
    params: [{ key: "length", label: "ATR length", type: "int", default: 10, min: 1, max: 200 },
      { key: "factor", label: "Factor", type: "float", default: 3, min: 0.1, max: 20, step: 0.1 }],
    plots: [
      { key: "up", title: "Up trend", kind: "line", color: C.green, width: 2 },
      { key: "down", title: "Down trend", kind: "line", color: C.red, width: 2 },
    ],
    compute: (b, p) => {
      const r = atr(b, Math.round(P(p, "length", 10)));
      const f = P(p, "factor", 3);
      const n = b.c.length;
      const up = nulls(n);
      const dn = nulls(n);
      let prevLower = NaN;
      let prevUpper = NaN;
      let prevSt = NaN;
      let prevAtrValid = false;
      for (let i = 0; i < n; i++) {
        const a = r[i];
        if (a == null) {
          prevAtrValid = false;
          continue;
        }
        const mid = (b.h[i]! + b.l[i]!) / 2;
        const pl = Number.isNaN(prevLower) ? 0 : prevLower;
        const pu = Number.isNaN(prevUpper) ? 0 : prevUpper;
        const prevClose = b.c[i - 1] ?? b.c[i]!;
        let lb = mid - f * a;
        let ub = mid + f * a;
        lb = lb > pl || prevClose < pl ? lb : pl;
        ub = ub < pu || prevClose > pu ? ub : pu;
        // direction: -1 = uptrend (line below price), 1 = downtrend (line above price)
        let dir: number;
        if (!prevAtrValid) dir = 1;
        else if (prevSt === pu) dir = b.c[i]! > ub ? -1 : 1;
        else dir = b.c[i]! < lb ? 1 : -1;
        const st = dir === -1 ? lb : ub;
        if (dir === -1) up[i] = st;
        else dn[i] = st;
        prevLower = lb;
        prevUpper = ub;
        prevSt = st;
        prevAtrValid = true;
      }
      return { up, down: dn };
    },
  },
  {
    id: "PSAR", name: "Parabolic SAR", short: "SAR", category: "Trend", overlay: true,
    description: "Wilder's stop-and-reverse points: trail the trend and flip when price crosses them.",
    params: [{ key: "start", label: "Start", type: "float", default: 0.02, min: 0.001, max: 1, step: 0.001 },
      { key: "inc", label: "Increment", type: "float", default: 0.02, min: 0.001, max: 1, step: 0.001 },
      { key: "max", label: "Maximum", type: "float", default: 0.2, min: 0.01, max: 1, step: 0.01 }],
    plots: [{ key: "sar", title: "SAR", kind: "dots", color: C.blue, width: 1 }],
    compute: (b, p) => {
      const start = P(p, "start", 0.02);
      const inc = P(p, "inc", 0.02);
      const mx = P(p, "max", 0.2);
      const n = b.c.length;
      const out = nulls(n);
      if (n < 2) return { sar: out };
      let up = b.c[1]! >= b.c[0]!;
      let sar = up ? b.l[0]! : b.h[0]!;
      let ep = up ? b.h[1]! : b.l[1]!;
      let af = start;
      for (let i = 1; i < n; i++) {
        sar = sar + af * (ep - sar);
        if (up) {
          sar = Math.min(sar, b.l[i - 1]!, i > 1 ? b.l[i - 2]! : b.l[i - 1]!);
          if (b.l[i]! < sar) {
            up = false;
            sar = ep;
            ep = b.l[i]!;
            af = start;
          } else if (b.h[i]! > ep) {
            ep = b.h[i]!;
            af = Math.min(mx, af + inc);
          }
        } else {
          sar = Math.max(sar, b.h[i - 1]!, i > 1 ? b.h[i - 2]! : b.h[i - 1]!);
          if (b.h[i]! > sar) {
            up = true;
            sar = ep;
            ep = b.h[i]!;
            af = start;
          } else if (b.l[i]! < ep) {
            ep = b.l[i]!;
            af = Math.min(mx, af + inc);
          }
        }
        out[i] = sar;
      }
      return { sar: out };
    },
  },
  {
    id: "ICHI", name: "Ichimoku Cloud", short: "Ichimoku", category: "Trend", overlay: true,
    description: "Conversion, base, leading spans A/B (plotted 26 bars ahead) and lagging span (26 bars back). The cloud beyond the last bar is not projected.",
    params: [{ key: "conv", label: "Conversion", type: "int", default: 9, min: 1, max: 200 },
      { key: "base", label: "Base", type: "int", default: 26, min: 1, max: 200 },
      { key: "spanb", label: "Leading span B", type: "int", default: 52, min: 1, max: 400 },
      { key: "disp", label: "Displacement", type: "int", default: 26, min: 1, max: 200 }],
    plots: [
      { key: "conv", title: "Conversion", kind: "line", color: C.blue, width: 1 },
      { key: "base", title: "Base", kind: "line", color: C.red, width: 1 },
      { key: "spanA", title: "Lead A", kind: "line", color: C.green, width: 1 },
      { key: "spanB", title: "Lead B", kind: "line", color: C.red, width: 1, dashed: true },
      { key: "lag", title: "Lagging", kind: "line", color: C.gray, width: 1 },
    ],
    compute: (b, p) => {
      const donch = (n: number) => {
        const hh = highest(b.h, n);
        const ll = lowest(b.l, n);
        return hh.map((h, i) => (h == null || ll[i] == null ? null : (h + (ll[i] as number)) / 2));
      };
      const disp = Math.round(P(p, "disp", 26));
      const conv = donch(Math.round(P(p, "conv", 9)));
      const base = donch(Math.round(P(p, "base", 26)));
      const a = conv.map((c, i) => (c == null || base[i] == null ? null : (c + (base[i] as number)) / 2));
      const bb = donch(Math.round(P(p, "spanb", 52)));
      const shift = (x: Out, k: number): Out => x.map((_, i) => (i - k >= 0 && i - k < x.length ? x[i - k] ?? null : null));
      return { conv, base, spanA: shift(a, disp - 1), spanB: shift(bb, disp - 1), lag: shift(b.c, -(disp - 1)) };
    },
  },
  {
    id: "PIVOT", name: "Pivot Points Standard", short: "Pivots", category: "Trend", overlay: true,
    description: "Floor-trader pivots from the previous period's high, low and close (daily for intraday charts, monthly for daily, yearly for weekly/monthly).",
    params: [],
    plots: [
      { key: "r3", title: "R3", kind: "step", color: C.red, width: 1, dashed: true },
      { key: "r2", title: "R2", kind: "step", color: C.red, width: 1, dashed: true },
      { key: "r1", title: "R1", kind: "step", color: C.red, width: 1 },
      { key: "p", title: "P", kind: "step", color: C.orange, width: 1 },
      { key: "s1", title: "S1", kind: "step", color: C.green, width: 1 },
      { key: "s2", title: "S2", kind: "step", color: C.green, width: 1, dashed: true },
      { key: "s3", title: "S3", kind: "step", color: C.green, width: 1, dashed: true },
    ],
    compute: (b) => {
      const unit = b.unit === "min" ? "day" : b.unit === "D" ? "month" : "year";
      const n = b.c.length;
      const keys = b.t.map((t) => periodKey(t, unit));
      const res: Record<string, Out> = { p: nulls(n), r1: nulls(n), s1: nulls(n), r2: nulls(n), s2: nulls(n), r3: nulls(n), s3: nulls(n) };
      let prev: { h: number; l: number; c: number } | null = null;
      let cur: { h: number; l: number; c: number } | null = null;
      for (let i = 0; i < n; i++) {
        if (i === 0 || keys[i] !== keys[i - 1]) {
          prev = cur;
          cur = { h: b.h[i]!, l: b.l[i]!, c: b.c[i]! };
        } else if (cur) {
          cur = { h: Math.max(cur.h, b.h[i]!), l: Math.min(cur.l, b.l[i]!), c: b.c[i]! };
        }
        if (!prev) continue;
        const pp = (prev.h + prev.l + prev.c) / 3;
        const rng = prev.h - prev.l;
        res.p![i] = pp;
        res.r1![i] = 2 * pp - prev.l;
        res.s1![i] = 2 * pp - prev.h;
        res.r2![i] = pp + rng;
        res.s2![i] = pp - rng;
        res.r3![i] = prev.h + 2 * (pp - prev.l);
        res.s3![i] = prev.l - 2 * (prev.h - pp);
      }
      return res;
    },
  },
  // ---------------------------------------------------------------- oscillators
  {
    id: "VOL", name: "Volume", short: "Vol", category: "Volume", overlay: false,
    description: "Traded volume per bar (green when the bar closed up) with its moving average.",
    params: [{ key: "length", label: "MA length", type: "int", default: 20, min: 1, max: 500 }],
    plots: [
      { key: "vol", title: "Volume", kind: "histogram", color: UP },
      { key: "ma", title: "MA", kind: "line", color: C.blue, width: 1 },
    ],
    compute: (b, p) => ({ vol: b.v.slice(), ma: sma(b.v, Math.round(P(p, "length", 20))) }),
    barColor: (key, i, _o, b) => (key === "vol" ? (b.c[i]! >= b.o[i]! ? "rgba(38,166,154,0.55)" : "rgba(239,83,80,0.55)") : undefined),
  },
  {
    id: "RSI", name: "Relative Strength Index", short: "RSI", category: "Momentum", overlay: false,
    description: "Wilder's RSI: 100 − 100/(1 + avg gain/avg loss). Above 70 overbought, below 30 oversold.",
    params: [len(14), src()],
    plots: [{ key: "rsi", title: "RSI", kind: "line", color: C.purple, width: 2 }],
    levels: [{ value: 70 }, { value: 50, color: "rgba(120,123,134,0.35)" }, { value: 30 }],
    range: [0, 100],
    compute: (b, p) => ({ rsi: rsiOf(source(b, S(p)), Math.round(P(p, "length", 14))) }),
  },
  {
    id: "MACD", name: "MACD", short: "MACD", category: "Momentum", overlay: false,
    description: "EMA(fast) − EMA(slow), its EMA signal line and the histogram between them.",
    params: [{ key: "fast", label: "Fast", type: "int", default: 12, min: 1, max: 200 },
      { key: "slow", label: "Slow", type: "int", default: 26, min: 1, max: 400 },
      { key: "signal", label: "Signal", type: "int", default: 9, min: 1, max: 200 }, src()],
    plots: [
      { key: "hist", title: "Histogram", kind: "histogram", color: UP },
      { key: "macd", title: "MACD", kind: "line", color: C.blue, width: 2 },
      { key: "signal", title: "Signal", kind: "line", color: C.orange, width: 1 },
    ],
    levels: [{ value: 0, color: "rgba(120,123,134,0.35)" }],
    compute: (b, p) => {
      const x = source(b, S(p));
      const m = sub(ema(x, Math.round(P(p, "fast", 12))), ema(x, Math.round(P(p, "slow", 26))));
      const s = ema(m, Math.round(P(p, "signal", 9)));
      return { macd: m, signal: s, hist: sub(m, s) };
    },
    barColor: (key, i, o) => {
      if (key !== "hist") return undefined;
      const h = o.hist![i];
      const prev = o.hist![i - 1];
      if (h == null) return undefined;
      if (h >= 0) return prev != null && h < prev ? "rgba(38,166,154,0.45)" : UP;
      return prev != null && h > prev ? "rgba(239,83,80,0.45)" : DOWN;
    },
  },
  {
    id: "STOCH", name: "Stochastic", short: "Stoch", category: "Momentum", overlay: false,
    description: "%K = position of the close within the n-bar range (smoothed); %D = SMA of %K.",
    params: [{ key: "k", label: "%K length", type: "int", default: 14, min: 1, max: 200 },
      { key: "smooth", label: "%K smoothing", type: "int", default: 1, min: 1, max: 50 },
      { key: "d", label: "%D smoothing", type: "int", default: 3, min: 1, max: 50 }],
    plots: [{ key: "k", title: "%K", kind: "line", color: C.blue, width: 1 }, { key: "d", title: "%D", kind: "line", color: C.orange, width: 1 }],
    levels: [{ value: 80 }, { value: 20 }],
    range: [0, 100],
    compute: (b, p) => {
      const n = Math.round(P(p, "k", 14));
      const hh = highest(b.h, n);
      const ll = lowest(b.l, n);
      const raw = b.c.map((c, i) => (hh[i] == null || ll[i] == null ? null : hh[i] === ll[i] ? 50 : (100 * (c - (ll[i] as number))) / ((hh[i] as number) - (ll[i] as number))));
      const k = sma(raw, Math.round(P(p, "smooth", 1)));
      return { k, d: sma(k, Math.round(P(p, "d", 3))) };
    },
  },
  {
    id: "STOCHRSI", name: "Stochastic RSI", short: "Stoch RSI", category: "Momentum", overlay: false,
    description: "Stochastic applied to the RSI.",
    params: [{ key: "k", label: "K", type: "int", default: 3, min: 1, max: 50 }, { key: "d", label: "D", type: "int", default: 3, min: 1, max: 50 },
      { key: "rsi", label: "RSI length", type: "int", default: 14, min: 1, max: 200 }, { key: "stoch", label: "Stochastic length", type: "int", default: 14, min: 1, max: 200 }, src()],
    plots: [{ key: "k", title: "K", kind: "line", color: C.blue, width: 1 }, { key: "d", title: "D", kind: "line", color: C.orange, width: 1 }],
    levels: [{ value: 80 }, { value: 20 }],
    range: [0, 100],
    compute: (b, p) => {
      const r = rsiOf(source(b, S(p)), Math.round(P(p, "rsi", 14)));
      const n = Math.round(P(p, "stoch", 14));
      const hh = highest(r, n);
      const ll = lowest(r, n);
      const raw = r.map((v, i) => (v == null || hh[i] == null || ll[i] == null ? null : hh[i] === ll[i] ? 50 : (100 * (v - (ll[i] as number))) / ((hh[i] as number) - (ll[i] as number))));
      const k = sma(raw, Math.round(P(p, "k", 3)));
      return { k, d: sma(k, Math.round(P(p, "d", 3))) };
    },
  },
  {
    id: "CCI", name: "Commodity Channel Index", short: "CCI", category: "Momentum", overlay: false,
    description: "(Typical price − SMA) / (0.015 × mean absolute deviation).",
    params: [len(20), src("hlc3")],
    plots: [{ key: "cci", title: "CCI", kind: "line", color: C.blue, width: 1 }],
    levels: [{ value: 100 }, { value: 0, color: "rgba(120,123,134,0.35)" }, { value: -100 }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 20));
      const x = source(b, S(p, "hlc3"));
      const m = sma(x, n);
      const out = nulls(x.length);
      for (let i = n - 1; i < x.length; i++) {
        const mu = m[i];
        if (mu == null) continue;
        let md = 0;
        for (let k = 0; k < n; k++) md += Math.abs(x[i - k]! - mu);
        md /= n;
        out[i] = md === 0 ? 0 : (x[i]! - mu) / (0.015 * md);
      }
      return { cci: out };
    },
  },
  {
    id: "WPR", name: "Williams %R", short: "%R", category: "Momentum", overlay: false,
    description: "−100 × (highest high − close) / (highest high − lowest low).",
    params: [len(14)],
    plots: [{ key: "wr", title: "%R", kind: "line", color: C.purple, width: 1 }],
    levels: [{ value: -20 }, { value: -80 }],
    range: [-100, 0],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 14));
      const hh = highest(b.h, n);
      const ll = lowest(b.l, n);
      return { wr: b.c.map((c, i) => (hh[i] == null || ll[i] == null ? null : hh[i] === ll[i] ? -50 : (-100 * ((hh[i] as number) - c)) / ((hh[i] as number) - (ll[i] as number)))) };
    },
  },
  {
    id: "ROC", name: "Rate of Change", short: "ROC", category: "Momentum", overlay: false,
    description: "Percentage change over n bars.",
    params: [len(9), src()],
    plots: [{ key: "roc", title: "ROC", kind: "line", color: C.blue, width: 1 }],
    levels: [{ value: 0, color: "rgba(120,123,134,0.35)" }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 9));
      const x = source(b, S(p));
      return { roc: x.map((v, i) => (i < n || !x[i - n] ? null : (100 * (v - x[i - n]!)) / x[i - n]!)) };
    },
  },
  {
    id: "MOM", name: "Momentum", short: "Mom", category: "Momentum", overlay: false,
    description: "Price change over n bars.",
    params: [len(10), src()],
    plots: [{ key: "mom", title: "Momentum", kind: "line", color: C.blue, width: 1 }],
    levels: [{ value: 0, color: "rgba(120,123,134,0.35)" }],
    compute: (b, p) => ({ mom: change(source(b, S(p)), Math.round(P(p, "length", 10))) }),
  },
  {
    id: "AO", name: "Awesome Oscillator", short: "AO", category: "Momentum", overlay: false,
    description: "SMA(hl2, 5) − SMA(hl2, 34); bars green when rising.",
    params: [],
    plots: [{ key: "ao", title: "AO", kind: "histogram", color: UP }],
    compute: (b) => {
      const x = source(b, "hl2");
      return { ao: sub(sma(x, 5), sma(x, 34)) };
    },
    barColor: (_k, i, o) => {
      const v = o.ao![i];
      const prev = o.ao![i - 1];
      if (v == null) return undefined;
      return prev == null || v >= prev ? UP : DOWN;
    },
  },
  {
    id: "TRIX", name: "TRIX", short: "TRIX", category: "Momentum", overlay: false,
    description: "Rate of change (×10,000) of a triple-smoothed EMA of log price.",
    params: [len(18)],
    plots: [{ key: "trix", title: "TRIX", kind: "line", color: C.red, width: 1 }],
    levels: [{ value: 0, color: "rgba(120,123,134,0.35)" }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 18));
      const e = ema(ema(ema(b.c.map((c) => Math.log(c)), n), n), n);
      return { trix: change(e).map((v) => (v == null ? null : v * 10000)) };
    },
  },
  {
    id: "UO", name: "Ultimate Oscillator", short: "UO", category: "Momentum", overlay: false,
    description: "Weighted average of buying pressure over three windows.",
    params: [{ key: "fast", label: "Fast", type: "int", default: 7, min: 1, max: 100 },
      { key: "mid", label: "Middle", type: "int", default: 14, min: 1, max: 100 },
      { key: "slow", label: "Slow", type: "int", default: 28, min: 1, max: 200 }],
    plots: [{ key: "uo", title: "UO", kind: "line", color: C.red, width: 1 }],
    levels: [{ value: 70 }, { value: 30 }],
    range: [0, 100],
    compute: (b, p) => {
      const n = b.c.length;
      const bp: Out = nulls(n);
      const tr: Out = nulls(n);
      for (let i = 1; i < n; i++) {
        const lo = Math.min(b.l[i]!, b.c[i - 1]!);
        const hi = Math.max(b.h[i]!, b.c[i - 1]!);
        bp[i] = b.c[i]! - lo;
        tr[i] = hi - lo;
      }
      const avg = (k: number) => {
        const a = sma(bp, k);
        const t = sma(tr, k);
        return a.map((v, i) => (v == null || !t[i] ? null : v / (t[i] as number)));
      };
      const a1 = avg(Math.round(P(p, "fast", 7)));
      const a2 = avg(Math.round(P(p, "mid", 14)));
      const a3 = avg(Math.round(P(p, "slow", 28)));
      return { uo: a1.map((v, i) => (v == null || a2[i] == null || a3[i] == null ? null : (100 * (4 * v + 2 * (a2[i] as number) + (a3[i] as number))) / 7)) };
    },
  },
  {
    id: "ADX", name: "ADX / DMI", short: "ADX", category: "Trend", overlay: false,
    description: "Average directional index (trend strength) with +DI and −DI (Wilder).",
    params: [{ key: "length", label: "DI length", type: "int", default: 14, min: 1, max: 200 },
      { key: "smoothing", label: "ADX smoothing", type: "int", default: 14, min: 1, max: 200 }],
    plots: [
      { key: "adx", title: "ADX", kind: "line", color: C.red, width: 2 },
      { key: "plus", title: "+DI", kind: "line", color: C.blue, width: 1 },
      { key: "minus", title: "−DI", kind: "line", color: C.orange, width: 1 },
    ],
    levels: [{ value: 25, color: "rgba(120,123,134,0.35)" }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 14));
      const len2 = b.c.length;
      const pdm: Out = nulls(len2);
      const mdm: Out = nulls(len2);
      for (let i = 1; i < len2; i++) {
        const up = b.h[i]! - b.h[i - 1]!;
        const dn = b.l[i - 1]! - b.l[i]!;
        pdm[i] = up > dn && up > 0 ? up : 0;
        mdm[i] = dn > up && dn > 0 ? dn : 0;
      }
      const tr = rma(trueRange(b).map((v, i) => (i === 0 ? null : v)), n);
      const plus = rma(pdm, n).map((v, i) => (v == null || !tr[i] ? null : (100 * v) / (tr[i] as number)));
      const minus = rma(mdm, n).map((v, i) => (v == null || !tr[i] ? null : (100 * v) / (tr[i] as number)));
      const dx = plus.map((v, i) => (v == null || minus[i] == null ? null : v + (minus[i] as number) === 0 ? 0 : (100 * Math.abs(v - (minus[i] as number))) / (v + (minus[i] as number))));
      return { adx: rma(dx, Math.round(P(p, "smoothing", 14))), plus, minus };
    },
  },
  {
    id: "AROON", name: "Aroon", short: "Aroon", category: "Trend", overlay: false,
    description: "How recently the n-bar high (Up) and low (Down) occurred, in % of n.",
    params: [len(14)],
    plots: [{ key: "up", title: "Up", kind: "line", color: C.orange, width: 1 }, { key: "down", title: "Down", kind: "line", color: C.blue, width: 1 }],
    range: [0, 100],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 14));
      const up = nulls(b.c.length);
      const dn = nulls(b.c.length);
      for (let i = n; i < b.c.length; i++) {
        let hi = i;
        let lo = i;
        for (let k = i - n; k <= i; k++) {
          if (b.h[k]! >= b.h[hi]!) hi = k;
          if (b.l[k]! <= b.l[lo]!) lo = k;
        }
        up[i] = (100 * (n - (i - hi))) / n;
        dn[i] = (100 * (n - (i - lo))) / n;
      }
      return { up, down: dn };
    },
  },
  {
    id: "ATR", name: "Average True Range", short: "ATR", category: "Volatility", overlay: false,
    description: "Wilder-smoothed true range.",
    params: [len(14)],
    plots: [{ key: "atr", title: "ATR", kind: "line", color: C.red, width: 1 }],
    compute: (b, p) => ({ atr: atr(b, Math.round(P(p, "length", 14))) }),
  },
  {
    id: "HV", name: "Historical Volatility", short: "HV", category: "Volatility", overlay: false,
    description: "Annualised standard deviation of log returns, in % (252 trading days a year).",
    params: [len(20)],
    plots: [{ key: "hv", title: "HV %", kind: "line", color: C.blue, width: 1 }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 20));
      const r: Out = b.c.map((c, i) => (i === 0 ? null : Math.log(c / b.c[i - 1]!)));
      const perYear = b.unit === "min" ? 252 * (375 * 60) / Math.max(60, b.barSeconds) : b.unit === "D" ? 252 : b.unit === "W" ? 52 : 12;
      // sample standard deviation of returns
      const out = nulls(r.length);
      for (let i = n; i < r.length; i++) {
        let s = 0;
        for (let k = 0; k < n; k++) s += r[i - k] as number;
        const mu = s / n;
        let ss = 0;
        for (let k = 0; k < n; k++) ss += ((r[i - k] as number) - mu) ** 2;
        out[i] = Math.sqrt(ss / (n - 1)) * Math.sqrt(perYear) * 100;
      }
      return { hv: out };
    },
  },
  {
    id: "BBW", name: "Bollinger %B & Bandwidth", short: "%B", category: "Volatility", overlay: false,
    description: "%B: where the close sits inside the bands (0 = lower, 1 = upper). Bandwidth: band width as % of the basis.",
    params: [len(20), { key: "mult", label: "StdDev", type: "float", default: 2, min: 0.1, max: 10, step: 0.1 }],
    plots: [{ key: "pctb", title: "%B", kind: "line", color: C.teal, width: 1 }, { key: "bw", title: "Bandwidth %", kind: "line", color: C.orange, width: 1 }],
    levels: [{ value: 1 }, { value: 0 }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 20));
      const k = P(p, "mult", 2);
      const m = sma(b.c, n);
      const sd = stdev(b.c, n);
      return {
        pctb: b.c.map((c, i) => (m[i] == null || !sd[i] ? null : (c - ((m[i] as number) - k * (sd[i] as number))) / (2 * k * (sd[i] as number)))),
        bw: m.map((v, i) => (v == null || sd[i] == null ? null : (100 * 2 * k * (sd[i] as number)) / v)),
      };
    },
  },
  {
    id: "OBV", name: "On-Balance Volume", short: "OBV", category: "Volume", overlay: false,
    description: "Running total of volume, added on up closes and subtracted on down closes.",
    params: [],
    plots: [{ key: "obv", title: "OBV", kind: "line", color: C.blue, width: 1 }],
    compute: (b) => {
      let acc = 0;
      return { obv: b.c.map((c, i) => (i === 0 ? (acc = 0) : (acc += c > b.c[i - 1]! ? b.v[i]! : c < b.c[i - 1]! ? -b.v[i]! : 0))) };
    },
  },
  {
    id: "MFI", name: "Money Flow Index", short: "MFI", category: "Volume", overlay: false,
    description: "Volume-weighted RSI of the typical price.",
    params: [len(14)],
    plots: [{ key: "mfi", title: "MFI", kind: "line", color: C.purple, width: 1 }],
    levels: [{ value: 80 }, { value: 20 }],
    range: [0, 100],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 14));
      const tp = source(b, "hlc3");
      const out = nulls(tp.length);
      for (let i = n; i < tp.length; i++) {
        let pos = 0;
        let neg = 0;
        for (let k = i - n + 1; k <= i; k++) {
          const mf = tp[k]! * b.v[k]!;
          if (tp[k]! > tp[k - 1]!) pos += mf;
          else if (tp[k]! < tp[k - 1]!) neg += mf;
        }
        out[i] = neg === 0 ? (pos === 0 ? 50 : 100) : 100 - 100 / (1 + pos / neg);
      }
      return { mfi: out };
    },
  },
  {
    id: "CMF", name: "Chaikin Money Flow", short: "CMF", category: "Volume", overlay: false,
    description: "Sum of money-flow volume over n bars divided by total volume.",
    params: [len(20)],
    plots: [{ key: "cmf", title: "CMF", kind: "line", color: C.green, width: 1 }],
    levels: [{ value: 0, color: "rgba(120,123,134,0.35)" }],
    compute: (b, p) => {
      const n = Math.round(P(p, "length", 20));
      const mfv: Out = b.c.map((c, i) => {
        const r = b.h[i]! - b.l[i]!;
        return r === 0 ? 0 : (((c - b.l[i]!) - (b.h[i]! - c)) / r) * b.v[i]!;
      });
      const a = sma(mfv, n);
      const v = sma(b.v, n);
      return { cmf: a.map((x, i) => (x == null || !v[i] ? null : x / (v[i] as number))) };
    },
  },
];

export const INDICATOR_BY_ID: Record<string, IndicatorDef> = Object.fromEntries(INDICATORS.map((d) => [d.id, d]));

export function defaultParams(def: IndicatorDef): Params {
  return Object.fromEntries(def.params.map((p) => [p.key, p.default]));
}

export function indicatorLabel(def: IndicatorDef, params: Params): string {
  const vals = def.params.map((p) => params[p.key] ?? p.default).filter((v) => v !== "close");
  return vals.length ? `${def.short} ${vals.join(" ")}` : def.short;
}
