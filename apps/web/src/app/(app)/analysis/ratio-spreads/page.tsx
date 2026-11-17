"use client";
import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import * as React from "react";
import { UnderlyingExpiry } from "@/components/analysis/pickers";
import { PayoffPanel } from "@/components/analysis/payoff-panel";
import { Disclaimer, EmptyState } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Checkbox, Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiJson } from "@/lib/api";
import { inr, num } from "@/lib/format";
import type { PayoffLeg } from "@/lib/options";
import { cn } from "@/lib/utils";

interface Candidate {
  type: string;
  buy_strike: number;
  sell_strike: number;
  ratio: number;
  buy_premium: number;
  sell_premium: number;
  net_credit: number;
  net_credit_per_lot: number;
  max_profit: number;
  max_profit_per_lot: number;
  breakeven: number;
  lower_breakeven: number | null;
  net_delta: number;
  short_delta: number;
  distance_pct: number;
  legs: PayoffLeg[];
}
interface Resp { underlying: string; spot: number; expiry: string; lot_size: number; days_to_expiry?: number; candidates: Candidate[]; count: number }

export default function RatioSpreadsPage() {
  const [underlying, setUnderlying] = React.useState("NIFTY");
  const [expiry, setExpiry] = React.useState<string | undefined>(undefined);
  const [kind, setKind] = React.useState<"CE" | "PE">("CE");
  const [ratios, setRatios] = React.useState<number[]>([2, 3]);
  const [creditOnly, setCreditOnly] = React.useState(true);
  const [deltaMax, setDeltaMax] = React.useState(0.45);
  const [sel, setSel] = React.useState(0);
  const body = { underlying, expiry: expiry ?? null, kind, ratios, max_debit: creditOnly ? 0 : null, delta_min: 0.05, delta_max: deltaMax, limit: 40 };
  const q = useQuery({
    queryKey: ["ratio", body],
    queryFn: () => apiJson<Resp>("/api/analysis/ratio-spreads", { method: "POST", body: JSON.stringify(body) }),
  });
  React.useEffect(() => setSel(0), [underlying, expiry, kind, ratios, creditOnly, deltaMax]);
  const d = q.data;
  const c = d?.candidates[sel];
  const dte = d ? Math.max(0.05, (new Date(`${d.expiry}T15:30:00+05:30`).getTime() - Date.now()) / 86_400_000) : 0;
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Scale}
        title="Ratio Spread Finder"
        description="1×N call/put ratio spreads ranked by credit, distance and delta — with payoff and what-if"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <UnderlyingExpiry underlying={underlying} setUnderlying={setUnderlying} expiry={expiry} setExpiry={setExpiry} />
            <Field label="Side">
              <Select value={kind} onValueChange={(v) => setKind(v as "CE" | "PE")} options={[{ value: "CE", label: "Call ratio (CE)" }, { value: "PE", label: "Put ratio (PE)" }]} />
            </Field>
            <Field label="Ratios" className="min-w-0">
              <div className="flex h-9 items-center gap-3 text-xs">
                {[2, 3, 4].map((r) => (
                  <label key={r} className="flex items-center gap-1">
                    <Checkbox checked={ratios.includes(r)} onCheckedChange={(v) => setRatios(v ? [...ratios, r].sort() : ratios.filter((x) => x !== r))} />
                    1×{r}
                  </label>
                ))}
              </div>
            </Field>
            <Field label="Max short delta">
              <Input type="number" step={0.05} min={0.05} max={0.9} value={deltaMax} onChange={(e) => setDeltaMax(Number(e.target.value))} className="w-24" />
            </Field>
            <label className="flex h-9 items-center gap-2 self-end text-xs">
              <Checkbox checked={creditOnly} onCheckedChange={(v) => setCreditOnly(v === true)} /> Credit / zero-cost only
            </label>
          </>
        }
        csv={d ? { filename: `${underlying}-ratio-spreads`, rows: () => d.candidates.map(({ legs: _legs, ...r }) => r) } : undefined}
        ask={d ? { question: `Explain the risk/reward of the top ${underlying} ratio spreads, especially the unlimited-risk side.`, context: () => ({ spot: d.spot, expiry: d.expiry, top: d.candidates.slice(0, 6).map(({ legs: _l, ...r }) => r) }) } : undefined}
      />
      {!d ? (
        <Skeleton className="h-[600px]" />
      ) : d.candidates.length === 0 ? (
        <EmptyState icon={Scale} title="No candidates" description="Relax the delta filter, allow debit spreads or pick a later expiry." />
      ) : (
        <div className="grid gap-3 xl:grid-cols-5">
          <Card className="xl:col-span-3">
            <CardContent className="max-h-[640px] overflow-auto p-0 scrollbar-thin">
              <Table>
                <THead>
                  <TR>
                    <TH>Structure</TH>
                    <TH className="text-right">Buy</TH>
                    <TH className="text-right">Sell</TH>
                    <TH className="text-right">Net credit/lot</TH>
                    <TH className="text-right">Max profit/lot</TH>
                    <TH className="text-right">Breakeven</TH>
                    <TH className="text-right">Dist %</TH>
                    <TH className="text-right">Short Δ</TH>
                    <TH className="text-right">Net Δ</TH>
                  </TR>
                </THead>
                <TBody>
                  {d.candidates.map((r, i) => (
                    <TR key={`${r.buy_strike}-${r.sell_strike}-${r.ratio}`} onClick={() => setSel(i)} className={cn("cursor-pointer", i === sel && "bg-primary/10 hover:bg-primary/10")} aria-selected={i === sel}>
                      <TD className="font-medium">{r.type}</TD>
                      <TD className="num text-right">
                        {num(r.buy_strike, 0)} <span className="text-2xs text-muted-foreground">@{num(r.buy_premium)}</span>
                      </TD>
                      <TD className="num text-right">
                        {r.ratio}×{num(r.sell_strike, 0)} <span className="text-2xs text-muted-foreground">@{num(r.sell_premium)}</span>
                      </TD>
                      <TD className={cn("num text-right", r.net_credit >= 0 ? "text-profit" : "text-loss")}>{inr(r.net_credit_per_lot, { decimals: 0 })}</TD>
                      <TD className="num text-right text-profit">{inr(r.max_profit_per_lot, { decimals: 0 })}</TD>
                      <TD className="num text-right">
                        {num(r.breakeven, 0)}
                        {r.lower_breakeven ? <span className="block text-2xs text-muted-foreground">{num(r.lower_breakeven, 0)}</span> : null}
                      </TD>
                      <TD className="num text-right">{num(r.distance_pct)}%</TD>
                      <TD className="num text-right">{num(r.short_delta, 2)}</TD>
                      <TD className="num text-right">{num(r.net_delta, 2)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </CardContent>
          </Card>
          <div className="flex flex-col gap-3 xl:col-span-2">
            {c && (
              <PayoffPanel
                title={`${c.type}: buy ${num(c.buy_strike, 0)}, sell ${c.ratio}× ${num(c.sell_strike, 0)}`}
                spot={d.spot}
                legs={c.legs}
                lotSize={d.lot_size}
                daysToExpiry={dte}
              />
            )}
            <p className="rounded-md border border-loss/30 bg-loss/5 p-2 text-2xs text-loss">
              Ratio spreads have <strong>unlimited risk</strong> beyond the upper breakeven ({kind === "CE" ? "rally" : "crash"}). Size conservatively and use stop-losses.
            </p>
            <Disclaimer kind="options" />
          </div>
        </div>
      )}
    </div>
  );
}
