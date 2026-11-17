/** Black-Scholes + multi-leg payoff (mirrors strategy_engine/analytics/options.py) for instant what-if UI. */
export const RISK_FREE = 0.065;

export interface PayoffLeg {
  action: "BUY" | "SELL";
  option_type: "CE" | "PE" | "FUT";
  strike: number;
  premium: number;
  iv: number; // %
  lots: number;
  symbol?: string;
}

// Abramowitz-Stegun 7.1.26 based normal CDF (|err| < 7.5e-8)
export function ncdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp((-x * x) / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}

export function bsPrice(s: number, k: number, t: number, sigma: number, call: boolean, r = RISK_FREE): number {
  if (t <= 0 || sigma <= 0) return Math.max(0, call ? s - k : k - s);
  const sq = Math.sqrt(t);
  const d1 = (Math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sq);
  const d2 = d1 - sigma * sq;
  return call ? s * ncdf(d1) - k * Math.exp(-r * t) * ncdf(d2) : k * Math.exp(-r * t) * ncdf(-d2) - s * ncdf(-d1);
}

export function bsDelta(s: number, k: number, t: number, sigma: number, call: boolean, r = RISK_FREE): number {
  if (t <= 0 || sigma <= 0) return call ? (s > k ? 1 : 0) : s < k ? -1 : 0;
  const d1 = (Math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * Math.sqrt(t));
  return call ? ncdf(d1) : ncdf(d1) - 1;
}

export interface PayoffPoint {
  spot: number;
  expiry: number;
  t: number;
}

export function computePayoff(
  spot: number,
  legs: PayoffLeg[],
  lotSize: number,
  daysToExpiry: number,
  opts: { daysForward?: number; ivShift?: number; spotShiftPct?: number; rangePct?: number; points?: number } = {},
): { points: PayoffPoint[]; breakevens: number[]; maxProfit: number | null; maxLoss: number | null; netPremium: number; delta: number } {
  const { daysForward = 0, ivShift = 0, rangePct = 0.12, points = 161 } = opts;
  const tNow = Math.max(0, daysToExpiry / 365);
  const tFwd = Math.max(0, (daysToExpiry - daysForward) / 365);
  const lo = spot * (1 - rangePct);
  const step = (spot * 2 * rangePct) / (points - 1);
  const pts: PayoffPoint[] = [];
  let net = 0;
  for (const l of legs) net += (l.action === "BUY" ? -1 : 1) * l.premium * l.lots * lotSize;
  const legValue = (l: PayoffLeg, s: number, t: number) =>
    l.option_type === "FUT" ? s : bsPrice(s, l.strike, t, Math.max(0.01, (l.iv + ivShift) / 100), l.option_type === "CE");
  const intrinsic = (l: PayoffLeg, s: number) => (l.option_type === "FUT" ? s : l.option_type === "CE" ? Math.max(0, s - l.strike) : Math.max(0, l.strike - s));
  for (let i = 0; i < points; i++) {
    const s = lo + i * step;
    let e = 0;
    let t = 0;
    for (const l of legs) {
      const sign = l.action === "BUY" ? 1 : -1;
      const q = l.lots * lotSize;
      e += sign * (intrinsic(l, s) - l.premium) * q;
      t += sign * (legValue(l, s, tFwd) - l.premium) * q;
    }
    pts.push({ spot: Math.round(s * 100) / 100, expiry: Math.round(e * 100) / 100, t: Math.round(t * 100) / 100 });
  }
  const be: number[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]!;
    const b = pts[i]!;
    if ((a.expiry < 0 && b.expiry >= 0) || (a.expiry > 0 && b.expiry <= 0)) be.push(Math.round((a.spot - (a.expiry * (b.spot - a.spot)) / (b.expiry - a.expiry)) * 100) / 100);
  }
  // unbounded check on a wide grid
  const wide = (s: number) => legs.reduce((acc, l) => acc + (l.action === "BUY" ? 1 : -1) * (intrinsic(l, s) - l.premium) * l.lots * lotSize, 0);
  const up = wide(spot * 3) - wide(spot * 2.9);
  const dn = wide(spot * 0.01) - wide(spot * 0.02);
  const vals = Array.from({ length: 601 }, (_, i) => wide(spot * (0.4 + (i * 1.2) / 600)));
  const delta = legs.reduce((acc, l) => acc + (l.action === "BUY" ? 1 : -1) * l.lots * lotSize * (l.option_type === "FUT" ? 1 : bsDelta(spot, l.strike, Math.max(tFwd, 1e-6), Math.max(0.01, (l.iv + ivShift) / 100), l.option_type === "CE")), 0);
  return {
    points: pts,
    breakevens: be,
    maxProfit: up > 1e-6 || dn > 1e-6 ? null : Math.max(...vals),
    maxLoss: up < -1e-6 || dn < -1e-6 ? null : Math.min(...vals),
    netPremium: net,
    delta,
  };
  void tNow;
}
