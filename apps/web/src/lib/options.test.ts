import { describe, expect, it } from "vitest";
import { bsPrice, computePayoff } from "./options";

describe("options math", () => {
  it("satisfies put-call parity", () => {
    const [s, k, t, v, r] = [26000, 26100, 7 / 365, 0.13, 0.065];
    const c = bsPrice(s, k, t, v, true, r);
    const p = bsPrice(s, k, t, v, false, r);
    expect(c - p).toBeCloseTo(s - k * Math.exp(-r * t), 2);
  });
  it("bull call spread has bounded payoff and one breakeven", () => {
    const res = computePayoff(26000, [
      { action: "BUY", option_type: "CE", strike: 26000, premium: 150, iv: 13, lots: 1 },
      { action: "SELL", option_type: "CE", strike: 26300, premium: 60, iv: 12, lots: 1 },
    ], 65, 7);
    expect(res.breakevens).toHaveLength(1);
    expect(res.breakevens[0]).toBeCloseTo(26090, 0);
    expect(res.maxProfit).toBeCloseTo((300 - 90) * 65, 0);
    expect(res.maxLoss).toBeCloseTo(-90 * 65, 0);
  });
  it("flags unlimited risk on a short straddle", () => {
    const res = computePayoff(26000, [
      { action: "SELL", option_type: "CE", strike: 26000, premium: 150, iv: 13, lots: 1 },
      { action: "SELL", option_type: "PE", strike: 26000, premium: 140, iv: 13, lots: 1 },
    ], 65, 7);
    expect(res.maxLoss).toBeNull();
    expect(res.breakevens).toEqual([expect.closeTo(25710, 0), expect.closeTo(26290, 0)]);
  });
});
