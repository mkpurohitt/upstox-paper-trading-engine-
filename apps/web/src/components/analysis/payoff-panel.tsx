"use client";
import * as React from "react";
import { PayoffChart } from "@/components/charts/payoff-chart";
import { Stat } from "@/components/common";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/misc";
import { computePayoff, type PayoffLeg } from "@/lib/options";
import { inr, num } from "@/lib/format";

/** Client-side what-if payoff for a set of priced legs (instant slider response). */
export function PayoffPanel({
  spot,
  legs,
  lotSize,
  daysToExpiry,
  title = "Payoff",
  extra,
  pop,
}: {
  spot: number;
  legs: PayoffLeg[];
  lotSize: number;
  daysToExpiry: number;
  title?: string;
  extra?: React.ReactNode;
  pop?: number | null;
}) {
  const [daysForward, setDaysForward] = React.useState(0);
  const [ivShift, setIvShift] = React.useState(0);
  const autoRange = React.useMemo(() => {
    const iv = legs.length ? legs.reduce((a, l) => a + (l.iv || 15), 0) / legs.length : 15;
    return Math.max(2, Math.min(15, Math.round(4 * iv * Math.sqrt(Math.max(daysToExpiry, 0.05) / 365))));
  }, [legs, daysToExpiry]);
  const [range, setRange] = React.useState(autoRange);
  React.useEffect(() => setRange(autoRange), [autoRange]);
  const res = React.useMemo(
    () => computePayoff(spot, legs, lotSize, daysToExpiry, { daysForward: Math.min(daysForward, daysToExpiry), ivShift, rangePct: range / 100 }),
    [spot, legs, lotSize, daysToExpiry, daysForward, ivShift, range],
  );
  const maxDays = Math.max(0, Math.floor(daysToExpiry));
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        <div className="flex flex-wrap gap-1">
          {legs.map((l, i) => (
            <Badge key={i} variant={l.action === "BUY" ? "profit" : "loss"}>
              {l.action === "BUY" ? "+" : "−"}
              {l.lots} {l.option_type === "FUT" ? "FUT" : `${num(l.strike, 0)} ${l.option_type}`} @ {num(l.premium)}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <Stat label={res.netPremium >= 0 ? "Net credit" : "Net debit"} value={inr(Math.abs(res.netPremium), { decimals: 0 })} />
          <Stat label="Max profit" value={res.maxProfit === null ? "Unlimited" : inr(res.maxProfit, { decimals: 0 })} tone="profit" />
          <Stat label="Max loss" value={res.maxLoss === null ? "Unlimited" : inr(res.maxLoss, { decimals: 0 })} tone="loss" />
          <Stat label="Breakevens" value={res.breakevens.length ? res.breakevens.map((b) => num(b, 0)).join(" / ") : "—"} />
          <Stat label={pop !== undefined ? "POP · Δ" : "Net delta"} value={pop !== undefined && pop !== null ? `${num(pop * 100, 0)}% · ${num(res.delta, 2)}` : num(res.delta, 2)} hint="Δ in units of the underlying" />
        </div>
        <PayoffChart points={res.points} spot={spot} breakevens={res.breakevens} height={300} showT={daysForward < daysToExpiry} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={`Days forward: ${Math.min(daysForward, maxDays)} of ${num(daysToExpiry, 1)}`}>
            <Slider value={[daysForward]} min={0} max={Math.max(1, maxDays)} step={1} onValueChange={([v]) => setDaysForward(v ?? 0)} aria-label="Days forward" />
          </Field>
          <Field label={`IV shift: ${ivShift > 0 ? "+" : ""}${ivShift} pts`}>
            <Slider value={[ivShift]} min={-10} max={20} step={1} onValueChange={([v]) => setIvShift(v ?? 0)} aria-label="IV shift" />
          </Field>
          <Field label={`Price range: ±${range}%`}>
            <Slider value={[range]} min={2} max={30} step={1} onValueChange={([v]) => setRange(v ?? 8)} aria-label="Price range" />
          </Field>
        </div>
        {extra}
      </CardContent>
    </Card>
  );
}
