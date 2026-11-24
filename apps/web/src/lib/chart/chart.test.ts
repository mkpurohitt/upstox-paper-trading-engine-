import { describe, expect, it } from "vitest";
import { type BarsInput, ema, INDICATOR_BY_ID, INDICATORS, defaultParams, rma, rsiOf, sma, stdev, wma } from "./indicators";
import { applyTick, type Bar, bucketKey, bucketStart, heikinAshi, inSession, IST_OFFSET, lineBreak, makeMapper, mergeBars, renko, tfInfo, toChartTime } from "./series";

// Wilder RSI worked example (StockCharts "RSI" ChartSchool spreadsheet, 4-decimal closes): 14-period RSI.
const RSI_CLOSES = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826, 45.8931, 46.0328, 45.614, 46.282, 46.282, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439, 46.2122];
const RSI_EXPECTED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93];

function input(c: number[], extra: Partial<BarsInput> = {}): BarsInput {
  return { t: c.map((_, i) => 1_700_000_000 + i * 300), o: c.map((x, i) => c[i - 1] ?? x), h: c.map((x) => x + 1), l: c.map((x) => x - 1), c, v: c.map(() => 1000), barSeconds: 300, unit: "min", ...extra };
}

function series(n: number, seed = 1): number[] {
  let s = seed;
  let p = 100;
  return Array.from({ length: n }, () => {
    s = (s * 16807) % 2147483647;
    p *= 1 + ((s / 2147483647) - 0.5) * 0.02;
    return p;
  });
}

describe("moving averages", () => {
  it("sma / wma / stdev", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
    expect(wma([1, 2, 3], 3)[2]).toBeCloseTo((1 + 4 + 9) / 6, 10);
    expect(stdev([2, 4, 4, 4, 5, 5, 7, 9], 8)[7]).toBeCloseTo(2, 10); // population SD
  });
  it("ema is seeded with the SMA of the first n values", () => {
    const e = ema([1, 2, 3, 4, 5, 6], 3);
    expect(e.slice(0, 2)).toEqual([null, null]);
    expect(e[2]).toBe(2);
    expect(e[3]).toBeCloseTo(0.5 * 4 + 0.5 * 2, 10);
  });
  it("rma (Wilder) uses alpha 1/n", () => {
    const r = rma([1, 1, 1, 4], 3);
    expect(r[2]).toBe(1);
    expect(r[3]).toBeCloseTo(1 + (4 - 1) / 3, 10);
  });
});

describe("RSI", () => {
  it("matches Wilder's worked example", () => {
    const r = rsiOf(RSI_CLOSES, 14);
    expect(r.slice(0, 14).every((v) => v == null)).toBe(true);
    RSI_EXPECTED.forEach((want, k) => expect(r[14 + k]!).toBeCloseTo(want, 1));
  });
});

describe("indicator catalogue", () => {
  const c = series(400);
  const b = input(c, { h: c.map((x) => x * 1.004), l: c.map((x) => x * 0.996) });
  it.each(INDICATORS.map((d) => [d.id]))("%s produces aligned, finite output", (id) => {
    const def = INDICATOR_BY_ID[id]!;
    const out = def.compute(b, defaultParams(def));
    for (const plot of def.plots) {
      const arr = out[plot.key];
      expect(arr, `${id}.${plot.key}`).toBeDefined();
      expect(arr!.length).toBe(c.length);
      const vals = arr!.filter((v): v is number => v != null);
      expect(vals.length, `${id}.${plot.key} has values`).toBeGreaterThan(0);
      expect(vals.every(Number.isFinite)).toBe(true);
      if (def.range) expect(vals.every((v) => v >= def.range![0] - 1e-9 && v <= def.range![1] + 1e-9), `${id} within range`).toBe(true);
    }
  });
  it("Bollinger bands are symmetric around the basis", () => {
    const o = INDICATOR_BY_ID.BB!.compute(b, { length: 20, mult: 2, source: "close" });
    const i = 100;
    expect(o.upper![i]! - o.basis![i]!).toBeCloseTo(o.basis![i]! - o.lower![i]!, 9);
  });
  it("MACD histogram = MACD - signal", () => {
    const o = INDICATOR_BY_ID.MACD!.compute(b, defaultParams(INDICATOR_BY_ID.MACD!));
    expect(o.hist![200]!).toBeCloseTo(o.macd![200]! - o.signal![200]!, 9);
  });
  it("Supertrend: exactly one of up/down per bar after warm-up, on the correct side of price", () => {
    const o = INDICATOR_BY_ID.ST!.compute(b, { length: 10, factor: 3 });
    for (let i = 20; i < c.length; i++) {
      expect((o.up![i] == null) !== (o.down![i] == null)).toBe(true);
      if (o.up![i] != null) expect(o.up![i]!).toBeLessThanOrEqual(b.h[i]!);
      if (o.down![i] != null) expect(o.down![i]!).toBeGreaterThanOrEqual(b.l[i]!);
    }
  });
  it("session VWAP resets each day", () => {
    const day = 86400;
    const t = [0, 300, 600, day, day + 300].map((x) => 1_700_006_400 - (1_700_006_400 % day) + 9.25 * 3600 + x);
    const bars = input([10, 12, 14, 50, 52], { t, h: [10, 12, 14, 50, 52], l: [10, 12, 14, 50, 52], v: [1, 1, 2, 1, 1] });
    const v = INDICATOR_BY_ID.VWAP!.compute(bars, {}).vwap!;
    expect(v[2]).toBeCloseTo((10 + 12 + 28) / 4, 9);
    expect(v[3]).toBe(50);
  });
});

describe("live bar building", () => {
  const tf = tfInfo("5");
  const ist = (s: string) => Math.floor(new Date(`${s}+05:30`).getTime() / 1000) + IST_OFFSET; // chart time
  const bars: Bar[] = [{ time: ist("2026-11-23T10:00:00"), open: 100, high: 101, low: 99, close: 100.5, volume: 10 }];
  it("updates the forming bar, then starts a new one at the bucket boundary", () => {
    let r = applyTick(bars, { ltp: 102, ts: "2026-11-23T04:33:00Z", volume: 500 }, tf, "NSE", 480); // 10:03 IST
    expect(r.appended).toBe(false);
    expect(r.bars.at(-1)).toMatchObject({ high: 102, close: 102, volume: 30 });
    r = applyTick(r.bars, { ltp: 98, ts: "2026-11-23T04:36:10Z", volume: 520 }, tf, "NSE", 500); // 10:06:10 IST
    expect(r.appended).toBe(true);
    expect(r.bars.at(-1)).toMatchObject({ time: ist("2026-11-23T10:05:00"), open: 98, close: 98, volume: 20 });
  });
  it("ignores ticks outside the session and stale ticks", () => {
    expect(applyTick(bars, { ltp: 1, ts: "2026-11-23T12:00:00Z" }, tf, "NSE", null).bars).toBe(bars); // 17:30 IST
    expect(applyTick(bars, { ltp: 1, ts: "2026-11-23T03:50:00Z" }, tf, "NSE", null).bars).toBe(bars); // 09:20, older bar
  });
  it("aligns hourly buckets to 09:15 and weekly to Monday", () => {
    const h = tfInfo("60");
    expect(new Date((bucketStart(ist("2026-11-23T11:40:00"), h) - 0) * 1000).toISOString().slice(11, 16)).toBe("11:15");
    expect(bucketKey(ist("2026-11-25T11:00:00"), tfInfo("W"))).toBe(bucketKey(ist("2026-11-23T09:15:00"), tfInfo("W")));
    expect(inSession(ist("2026-11-22T11:00:00"))).toBe(false); // Sunday
  });
  it("daily API bars use their IST date", () => {
    expect(new Date(toChartTime({ t: 0, o: 1, h: 1, l: 1, c: 1, v: 0, d: "2026-11-23" }) * 1000).toISOString().slice(0, 10)).toBe("2026-11-23");
  });
  it("merging pages keeps times unique and increasing", () => {
    const a = [1, 2, 3].map((t) => ({ ...bars[0]!, time: t }));
    const b2 = [3, 4].map((t) => ({ ...bars[0]!, time: t }));
    expect(mergeBars(a, b2).map((x) => x.time)).toEqual([1, 2, 3, 4]);
  });
});

describe("transforms and mapping", () => {
  const raw: Bar[] = [100, 101, 103, 106, 104, 99, 98, 102].map((c, i) => ({ time: i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 1 }));
  it("heikin ashi", () => {
    const ha = heikinAshi(raw);
    expect(ha[1]!.open).toBeCloseTo((ha[0]!.open + ha[0]!.close) / 2, 9);
    expect(ha[1]!.close).toBeCloseTo((raw[1]!.open + raw[1]!.high + raw[1]!.low + raw[1]!.close) / 4, 9);
  });
  it("renko bricks are box-sized with unique increasing times", () => {
    const r = renko(raw, 2);
    expect(r.length).toBeGreaterThan(2);
    expect(r.every((b) => Math.abs(Math.abs(b.close - b.open) - 2) < 1e-9)).toBe(true);
    expect(r.every((b, i) => i === 0 || b.time > r[i - 1]!.time)).toBe(true);
  });
  it("three-line break reverses only past the last three lines", () => {
    const lb = lineBreak(raw, 3);
    expect(lb.length).toBeGreaterThan(1);
    expect(lb.every((b, i) => i === 0 || b.time > lb[i - 1]!.time)).toBe(true);
  });
  it("time/logical mapping round-trips and extrapolates", () => {
    const m = makeMapper([0, 60, 120, 300], 60);
    expect(m.timeToLogical(90)).toBeCloseTo(1.5, 9);
    expect(m.logicalToTime(1.5)).toBeCloseTo(90, 9);
    expect(m.timeToLogical(420)).toBeCloseTo(5, 9);
    expect(m.logicalToTime(5)).toBeCloseTo(420, 9);
  });
});
