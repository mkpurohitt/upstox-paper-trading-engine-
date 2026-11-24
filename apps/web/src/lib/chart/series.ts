/**
 * Bar data for the Charts terminal: API -> chart time, live-tick aggregation into the forming bar, and price
 * transforms (Heikin Ashi, Renko, Line break).
 *
 * Chart time is the IST wall-clock time expressed as a UTC timestamp (seconds), so axis labels read in Indian
 * market time on any computer. Intraday bars are bucketed from the session open (09:15 NSE/BSE, 09:00 MCX), exactly
 * like the API does, so live updates extend the same bars the server returned.
 */

export const IST_OFFSET = 19800;

export interface ApiBar {
  t: number; // UTC seconds
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  oi?: number;
  d?: string; // IST date for D/W/M bars
}

export interface Bar {
  time: number; // chart time
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TfInfo {
  code: string; // "5", "60", "D", "W", "M"
  unit: "min" | "D" | "W" | "M";
  minutes: number;
}

export const TIMEFRAMES: { code: string; label: string; group: string }[] = [
  { code: "1", label: "1m", group: "Minutes" },
  { code: "2", label: "2m", group: "Minutes" },
  { code: "3", label: "3m", group: "Minutes" },
  { code: "5", label: "5m", group: "Minutes" },
  { code: "10", label: "10m", group: "Minutes" },
  { code: "15", label: "15m", group: "Minutes" },
  { code: "30", label: "30m", group: "Minutes" },
  { code: "45", label: "45m", group: "Minutes" },
  { code: "60", label: "1h", group: "Hours" },
  { code: "120", label: "2h", group: "Hours" },
  { code: "180", label: "3h", group: "Hours" },
  { code: "240", label: "4h", group: "Hours" },
  { code: "D", label: "1D", group: "Days" },
  { code: "W", label: "1W", group: "Days" },
  { code: "M", label: "1M", group: "Days" },
];

export function tfInfo(code: string): TfInfo {
  if (code === "D" || code === "W" || code === "M") return { code, unit: code, minutes: 0 };
  const m = Math.max(1, Math.min(375, parseInt(code, 10) || 1));
  return { code: String(m), unit: "min", minutes: m };
}

export function tfLabel(code: string): string {
  return TIMEFRAMES.find((t) => t.code === code)?.label ?? (/^\d+$/.test(code) ? (Number(code) % 60 === 0 ? `${Number(code) / 60}h` : `${code}m`) : code);
}

export function barSeconds(tf: TfInfo): number {
  if (tf.unit === "D") return 86400;
  if (tf.unit === "W") return 7 * 86400;
  if (tf.unit === "M") return 30 * 86400;
  return tf.minutes * 60;
}

export function sessionOpenMinutes(exchange: string): number {
  return exchange.toUpperCase().startsWith("MCX") ? 540 : 555;
}

export function sessionCloseMinutes(exchange: string): number {
  return exchange.toUpperCase().startsWith("MCX") ? 1410 : 930;
}

export function exchangeOf(symbol: string): string {
  const ex = symbol.split(":")[0]!.toUpperCase();
  if (ex.startsWith("MCX")) return "MCX";
  if (ex.startsWith("BSE") || ex === "BFO") return "BSE";
  return "NSE";
}

export function toChartTime(b: ApiBar): number {
  if (b.d) {
    const [y, m, d] = b.d.split("-").map(Number);
    return Date.UTC(y!, m! - 1, d!) / 1000;
  }
  return b.t + IST_OFFSET;
}

export function toBars(rows: ApiBar[]): Bar[] {
  return rows.map((r) => ({ time: toChartTime(r), open: r.o, high: r.h, low: r.l, close: r.c, volume: r.v ?? 0 }));
}

/** Merge older pages in front of newer ones, keeping times strictly increasing. */
export function mergeBars(older: Bar[], newer: Bar[]): Bar[] {
  if (!older.length) return newer;
  if (!newer.length) return older;
  const first = newer[0]!.time;
  return [...older.filter((b) => b.time < first), ...newer];
}

/** Bucket key of a chart time for the timeframe (same key = same bar). */
export function bucketKey(chartTime: number, tf: TfInfo, exchange = "NSE"): number {
  const day = Math.floor(chartTime / 86400);
  if (tf.unit === "D") return day;
  if (tf.unit === "W") {
    const weekday = (day + 3) % 7; // 0 = Monday (1970-01-01 was a Thursday)
    return day - weekday;
  }
  if (tf.unit === "M") {
    const d = new Date(chartTime * 1000);
    return d.getUTCFullYear() * 12 + d.getUTCMonth();
  }
  const open = sessionOpenMinutes(exchange);
  const mins = (chartTime - day * 86400) / 60 - open;
  const idx = mins < 0 ? 0 : Math.floor(mins / tf.minutes);
  return day * 10000 + idx;
}

/** Chart time at which a new bar containing `chartTime` starts. */
export function bucketStart(chartTime: number, tf: TfInfo, exchange = "NSE"): number {
  const day = Math.floor(chartTime / 86400);
  if (tf.unit !== "min") return day * 86400; // D/W/M bars are stamped with the day the first tick arrives
  const open = sessionOpenMinutes(exchange);
  const mins = (chartTime - day * 86400) / 60 - open;
  const idx = mins < 0 ? 0 : Math.floor(mins / tf.minutes);
  return day * 86400 + (open + idx * tf.minutes) * 60;
}

export function inSession(chartTime: number, exchange = "NSE"): boolean {
  const day = Math.floor(chartTime / 86400);
  const weekday = (day + 3) % 7;
  if (weekday > 4) return false;
  const mins = (chartTime - day * 86400) / 60;
  return mins >= sessionOpenMinutes(exchange) && mins < sessionCloseMinutes(exchange);
}

export interface LiveTick {
  ltp: number;
  ts: string; // ISO (UTC)
  volume?: number | null; // cumulative day volume
}

/**
 * Fold a tick into the bar list. Returns the updated array (same array when nothing changed) and whether a new bar
 * was started. `prevCumVolume` is the previous tick's cumulative day volume (null on the first tick).
 */
export function applyTick(bars: Bar[], tick: LiveTick, tf: TfInfo, exchange: string, prevCumVolume: number | null): { bars: Bar[]; appended: boolean } {
  if (!bars.length || !Number.isFinite(tick.ltp) || tick.ltp <= 0) return { bars, appended: false };
  const t = Math.floor(new Date(tick.ts).getTime() / 1000) + IST_OFFSET;
  if (!Number.isFinite(t) || !inSession(t, exchange)) return { bars, appended: false };
  const last = bars[bars.length - 1]!;
  const dv = tick.volume != null && prevCumVolume != null ? Math.max(0, tick.volume - prevCumVolume) : 0;
  const key = bucketKey(t, tf, exchange);
  const lastKey = bucketKey(last.time, tf, exchange);
  if (key === lastKey) {
    const upd: Bar = { ...last, high: Math.max(last.high, tick.ltp), low: Math.min(last.low, tick.ltp), close: tick.ltp, volume: last.volume + dv };
    const out = bars.slice();
    out[out.length - 1] = upd;
    return { bars: out, appended: false };
  }
  if (key < lastKey) return { bars, appended: false }; // late tick for an older bar
  const start = bucketStart(t, tf, exchange);
  if (start <= last.time) return { bars, appended: false };
  return { bars: [...bars, { time: start, open: tick.ltp, high: tick.ltp, low: tick.ltp, close: tick.ltp, volume: dv }], appended: true };
}

// ------------------------------------------------------------------------------------------------ transforms
export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]!;
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = i === 0 ? (b.open + b.close) / 2 : (out[i - 1]!.open + out[i - 1]!.close) / 2;
    out.push({ time: b.time, open, close, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close), volume: b.volume });
  }
  return out;
}

/** Close-based Renko with a fixed box. Bricks formed on the same bar get +1 s offsets so times stay unique. */
export function renko(bars: Bar[], box: number): Bar[] {
  if (!bars.length || !(box > 0)) return [];
  const out: Bar[] = [];
  let top = Math.round(bars[0]!.close / box) * box;
  let bottom = top;
  let dir = 0;
  for (const b of bars) {
    let k = 0;
    const push = (o: number, c: number) => {
      out.push({ time: b.time + k, open: o, close: c, high: Math.max(o, c), low: Math.min(o, c), volume: b.volume });
      k++;
    };
    for (;;) {
      if (dir >= 0 && b.close >= top + box) {
        push(top, top + box);
        bottom = top;
        top += box;
        dir = 1;
      } else if (dir <= 0 && b.close <= bottom - box) {
        push(bottom, bottom - box);
        top = bottom;
        bottom -= box;
        dir = -1;
      } else if (dir === 1 && b.close <= bottom - box) {
        push(bottom, bottom - box);
        top = bottom;
        bottom -= box;
        dir = -1;
      } else if (dir === -1 && b.close >= top + box) {
        push(top, top + box);
        bottom = top;
        top += box;
        dir = 1;
      } else break;
    }
  }
  return out;
}

/** n-line break chart (default 3). */
export function lineBreak(bars: Bar[], n = 3): Bar[] {
  const out: Bar[] = [];
  if (!bars.length) return out;
  let base = bars[0]!.close;
  for (const b of bars.slice(1)) {
    const c = b.close;
    if (!out.length) {
      if (c !== base) out.push({ time: b.time, open: base, close: c, high: Math.max(base, c), low: Math.min(base, c), volume: b.volume });
      continue;
    }
    const last = out[out.length - 1]!;
    const up = last.close > last.open;
    const recent = out.slice(-n);
    const hi = Math.max(...recent.map((x) => x.high));
    const lo = Math.min(...recent.map((x) => x.low));
    if (up) {
      if (c > last.close) out.push({ time: b.time, open: last.close, close: c, high: c, low: last.close, volume: b.volume });
      else if (c < lo) out.push({ time: b.time, open: last.open, close: c, high: last.open, low: c, volume: b.volume });
    } else {
      if (c < last.close) out.push({ time: b.time, open: last.close, close: c, high: last.close, low: c, volume: b.volume });
      else if (c > hi) out.push({ time: b.time, open: last.open, close: c, high: c, low: last.open, volume: b.volume });
    }
    base = c;
  }
  return out;
}

/** Time <-> logical index mapping over sorted bar times (fractional between bars, extrapolated beyond the ends). */
export function makeMapper(times: number[], step: number) {
  const n = times.length;
  return {
    timeToLogical(t: number): number | null {
      if (!n) return null;
      if (t <= times[0]!) return (t - times[0]!) / step;
      if (t >= times[n - 1]!) return n - 1 + (t - times[n - 1]!) / step;
      let lo = 0;
      let hi = n - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (times[mid]! <= t) lo = mid;
        else hi = mid;
      }
      const span = times[hi]! - times[lo]!;
      return lo + (span > 0 ? (t - times[lo]!) / span : 0);
    },
    logicalToTime(l: number): number | null {
      if (!n) return null;
      if (l <= 0) return times[0]! + l * step;
      if (l >= n - 1) return times[n - 1]! + (l - (n - 1)) * step;
      const i = Math.floor(l);
      const f = l - i;
      return times[i]! + f * (times[i + 1]! - times[i]!);
    },
  };
}

export function fmtPrice(p: number | null | undefined, digits = 2): string {
  if (p == null || !Number.isFinite(p)) return "—";
  return p.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtVolume(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)}L`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}
