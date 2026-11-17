import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";
import { compactInr, inr, pct, sym } from "./format";

describe("formatting", () => {
  it("uses Indian digit grouping and compact lakh/crore units", () => {
    expect(inr(1234567.5)).toBe("₹12,34,567.50");
    expect(compactInr(12_500_000)).toBe("₹1.25 Cr");
    expect(compactInr(-250_000)).toBe("-₹2.50 L");
    expect(pct(1.234)).toBe("+1.23%");
    expect(sym("NSE_INDEX:NIFTY")).toBe("NIFTY");
  });
  it("escapes CSV and neutralises formula injection", () => {
    const csv = toCsv([{ a: "=HYPERLINK(1)", b: 'x,"y"', c: -5 }]);
    expect(csv.split("\n")[1]).toBe(`'=HYPERLINK(1),"x,""y""",-5`);
  });
});
