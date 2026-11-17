"use client";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Hammer, Shapes } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { UnderlyingExpiry } from "@/components/analysis/pickers";
import { PayoffPanel } from "@/components/analysis/payoff-panel";
import { Disclaimer, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiJson } from "@/lib/api";
import { inr, num } from "@/lib/format";
import type { PayoffLeg } from "@/lib/options";
import { optionsDraft, sendDraftToBuilder } from "@/lib/options-draft";
import { cn } from "@/lib/utils";

export interface PayoffResp {
  spot: number;
  lot_size: number;
  net_premium: number;
  points: { spot: number; expiry: number; t: number }[];
  breakevens: number[];
  max_profit: number | null;
  max_loss: number | null;
  pop: number | null;
  greeks: { delta: number; gamma: number; theta: number; vega: number };
  days_to_expiry: number;
  underlying: string;
  expiry: string;
  expiries: string[];
  legs: (PayoffLeg & { offset?: number | null })[];
  structures: string[];
}

const STRUCTS = [
  { id: "iron_condor", label: "Iron condor", width: true, wing: true },
  { id: "iron_fly", label: "Iron butterfly", width: false, wing: true },
  { id: "long_call_butterfly", label: "Long call butterfly", width: false, wing: true },
  { id: "short_strangle", label: "Short strangle (unhedged)", width: true, wing: false },
] as const;

const fetchPayoff = (underlying: string, expiry: string | undefined, structure: string, width: number, wing: number) =>
  apiJson<PayoffResp>("/api/analysis/payoff", { method: "POST", body: JSON.stringify({ underlying, expiry: expiry ?? null, structure, width, wing }) });

export default function FlyCondorPage() {
  const router = useRouter();
  const [underlying, setUnderlying] = React.useState("NIFTY");
  const [expiry, setExpiry] = React.useState<string | undefined>(undefined);
  const [structure, setStructure] = React.useState<string>("iron_condor");
  const [width, setWidth] = React.useState(3);
  const [wing, setWing] = React.useState(3);
  const meta = STRUCTS.find((s) => s.id === structure) ?? STRUCTS[0];
  const q = useQuery({
    queryKey: ["flycondor", underlying, expiry, structure, width, wing],
    queryFn: () => fetchPayoff(underlying, expiry, structure, width, wing),
    refetchInterval: 15_000,
  });
  const compare = useQueries({
    queries: STRUCTS.map((s) => ({
      queryKey: ["flycondor", underlying, expiry, s.id, width, wing],
      queryFn: () => fetchPayoff(underlying, expiry, s.id, width, wing),
      staleTime: 15_000,
    })),
  });
  const d = q.data;
  const step = d && d.legs.length > 1 ? Math.min(...d.legs.flatMap((a) => d.legs.map((b) => Math.abs(a.strike - b.strike))).filter((x) => x > 0)) : 50;
  const atm = d ? d.legs.find((l) => (l.offset ?? 1) === 0)?.strike ?? Math.round(d.spot / step) * step : 0;
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Shapes}
        title="Butterfly & Condor Builder"
        description="Defined-risk neutral structures priced off the live chain: payoff, Greeks, probability of profit"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <UnderlyingExpiry underlying={underlying} setUnderlying={setUnderlying} expiry={expiry} setExpiry={setExpiry} />
            <Field label="Structure">
              <Select value={structure} onValueChange={setStructure} options={STRUCTS.map((s) => ({ value: s.id, label: s.label }))} />
            </Field>
            {meta.width && (
              <Field label="Short strikes from ATM">
                <Select value={String(width)} onValueChange={(v) => setWidth(Number(v))} options={[1, 2, 3, 4, 5, 6, 8, 10].map((n) => ({ value: String(n), label: `±${n}` }))} />
              </Field>
            )}
            {meta.wing && (
              <Field label="Wing width (strikes)">
                <Select value={String(wing)} onValueChange={(v) => setWing(Number(v))} options={[1, 2, 3, 4, 5, 6, 8].map((n) => ({ value: String(n), label: String(n) }))} />
              </Field>
            )}
            {d && (
              <Button variant="outline" size="sm" className="self-end" onClick={() => sendDraftToBuilder(optionsDraft(d.underlying, d.legs, atm, step, `${d.underlying} ${meta.label}`), router.push)}>
                <Hammer /> Backtest in Builder
              </Button>
            )}
          </>
        }
        csv={d ? { filename: `${underlying}-${structure}-payoff`, rows: () => d.points } : undefined}
        ask={d ? { question: `Evaluate this ${underlying} ${meta.label}: risk/reward, POP, Greeks and how to adjust if the market trends.`, context: () => ({ ...d, points: undefined, expiries: undefined, structures: undefined }) } : undefined}
      />
      {!d ? (
        <Skeleton className="h-[600px]" />
      ) : (
        <div className="grid gap-3 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <PayoffPanel title={`${meta.label} · ${d.underlying} ${d.expiry}`} spot={d.spot} legs={d.legs} lotSize={d.lot_size} daysToExpiry={Math.max(0.05, d.days_to_expiry)} pop={d.pop} />
          </div>
          <div className="flex flex-col gap-3">
            <Card>
              <CardHeader>
                <CardTitle>Position Greeks (per set)</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-2">
                <Stat label="Delta" value={num(d.greeks.delta, 3)} />
                <Stat label="Gamma" value={num(d.greeks.gamma, 4)} />
                <Stat label="Theta / day (₹)" value={num(d.greeks.theta, 0)} tone={d.greeks.theta >= 0 ? "profit" : "loss"} />
                <Stat label="Vega / 1 vol (₹)" value={num(d.greeks.vega, 0)} tone={d.greeks.vega >= 0 ? "profit" : "loss"} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Compare structures</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <THead>
                    <TR>
                      <TH>Structure</TH>
                      <TH className="text-right">Credit</TH>
                      <TH className="text-right">Max loss</TH>
                      <TH className="text-right">POP</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {STRUCTS.map((s, i) => {
                      const r = compare[i]?.data;
                      return (
                        <TR key={s.id} className={cn("cursor-pointer", s.id === structure && "bg-primary/10")} onClick={() => setStructure(s.id)}>
                          <TD className="text-xs font-medium">{s.label}</TD>
                          <TD className={cn("num text-right text-xs", (r?.net_premium ?? 0) >= 0 ? "text-profit" : "text-loss")}>{r ? inr(r.net_premium, { decimals: 0 }) : "…"}</TD>
                          <TD className="num text-right text-xs text-loss">{r ? (r.max_loss === null ? "Unlimited" : inr(r.max_loss, { decimals: 0 })) : "…"}</TD>
                          <TD className="num text-right text-xs">{r?.pop != null ? `${num(r.pop * 100, 0)}%` : "…"}</TD>
                        </TR>
                      );
                    })}
                  </TBody>
                </Table>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex flex-wrap gap-1 pt-4">
                {d.legs.map((l, i) => (
                  <Badge key={i} variant="outline" className="font-mono">
                    {l.symbol?.replace("NFO:", "").replace("BFO:", "")} · IV {num(l.iv, 1)}
                  </Badge>
                ))}
              </CardContent>
            </Card>
            <Disclaimer kind="options" />
          </div>
        </div>
      )}
    </div>
  );
}
