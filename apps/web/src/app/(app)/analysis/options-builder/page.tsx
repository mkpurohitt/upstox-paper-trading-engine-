"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical, Hammer, Plus, Trash2, Wrench } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { UnderlyingExpiry } from "@/components/analysis/pickers";
import { PayoffPanel } from "@/components/analysis/payoff-panel";
import { Disclaimer, EmptyState, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { api, apiJson, unwrap } from "@/lib/api";
import { inr, num } from "@/lib/format";
import type { PayoffLeg } from "@/lib/options";
import { optionsDraft, sendDraftToBuilder } from "@/lib/options-draft";
import { cn } from "@/lib/utils";

interface ChainLeg { symbol: string; ltp: number; iv: number | null }
interface ChainResp { chain: { underlying: string; spot: number; expiry: string; lot_size: number; atm_strike: number; rows: { strike: number; call: ChainLeg | null; put: ChainLeg | null }[] } }
interface ServerPayoff { pop: number | null; greeks: { delta: number; gamma: number; theta: number; vega: number } }
type BLeg = PayoffLeg & { manualPremium?: boolean };

const PRESETS: Record<string, { label: string; legs: [("BUY" | "SELL"), ("CE" | "PE"), number][] }> = {
  long_call: { label: "Long call", legs: [["BUY", "CE", 0]] },
  long_put: { label: "Long put", legs: [["BUY", "PE", 0]] },
  bull_call_spread: { label: "Bull call spread", legs: [["BUY", "CE", 0], ["SELL", "CE", 3]] },
  bear_put_spread: { label: "Bear put spread", legs: [["BUY", "PE", 0], ["SELL", "PE", -3]] },
  long_straddle: { label: "Long straddle", legs: [["BUY", "CE", 0], ["BUY", "PE", 0]] },
  short_straddle: { label: "Short straddle", legs: [["SELL", "CE", 0], ["SELL", "PE", 0]] },
  short_strangle: { label: "Short strangle", legs: [["SELL", "CE", 3], ["SELL", "PE", -3]] },
  long_strangle: { label: "Long strangle", legs: [["BUY", "CE", 3], ["BUY", "PE", -3]] },
  iron_condor: { label: "Iron condor", legs: [["SELL", "CE", 3], ["BUY", "CE", 6], ["SELL", "PE", -3], ["BUY", "PE", -6]] },
  iron_fly: { label: "Iron butterfly", legs: [["SELL", "CE", 0], ["SELL", "PE", 0], ["BUY", "CE", 4], ["BUY", "PE", -4]] },
  call_butterfly: { label: "Long call butterfly", legs: [["BUY", "CE", -2], ["SELL", "CE", 0], ["SELL", "CE", 0], ["BUY", "CE", 2]] },
  jade_lizard: { label: "Jade lizard", legs: [["SELL", "PE", -3], ["SELL", "CE", 2], ["BUY", "CE", 5]] },
};

export default function OptionsBuilderPage() {
  const router = useRouter();
  const [underlying, setUnderlying] = React.useState("NIFTY");
  const [expiry, setExpiry] = React.useState<string | undefined>(undefined);
  const [legs, setLegs] = React.useState<BLeg[]>([]);
  const [preset, setPreset] = React.useState("iron_condor");
  const chainQ = useQuery({
    queryKey: ["chain-builder", underlying, expiry],
    queryFn: () => apiJson<ChainResp>(`/api/analysis/option-chain?underlying=${underlying}&strikes=30${expiry ? `&expiry=${expiry}` : ""}`),
    refetchInterval: 10_000,
  });
  const chain = chainQ.data?.chain;
  const strikes = React.useMemo(() => chain?.rows.map((r) => r.strike) ?? [], [chain]);
  const step = strikes.length > 1 ? strikes[1]! - strikes[0]! : 50;

  const price = React.useCallback(
    (l: BLeg): BLeg => {
      if (!chain || l.option_type === "FUT") return l;
      const row = chain.rows.find((r) => r.strike === l.strike);
      const leg = row ? (l.option_type === "CE" ? row.call : row.put) : null;
      return { ...l, premium: l.manualPremium ? l.premium : leg?.ltp ?? l.premium, iv: leg?.iv ?? l.iv ?? 15, symbol: leg?.symbol };
    },
    [chain],
  );

  const applyPreset = React.useCallback(
    (key: string) => {
      if (!chain) return;
      const p = PRESETS[key];
      if (!p) return;
      setLegs(p.legs.map(([action, option_type, off]) => price({ action, option_type, strike: chain.atm_strike + off * step, lots: 1, premium: 0, iv: 15 })));
    },
    [chain, price, step],
  );

  // seed with the preset once the chain arrives / underlying changes
  const seeded = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (chain && seeded.current !== `${chain.underlying}:${chain.expiry}`) {
      seeded.current = `${chain.underlying}:${chain.expiry}`;
      applyPreset(preset);
    }
  }, [chain, applyPreset, preset]);
  // re-price live premiums on each chain refresh
  const priced = React.useMemo(() => legs.map(price), [legs, price]);

  const dte = chain ? Math.max(0.05, (new Date(`${chain.expiry}T15:30:00+05:30`).getTime() - Date.now()) / 86_400_000) : 1;
  const server = useQuery({
    queryKey: ["builder-payoff", underlying, chain?.expiry, priced.map((l) => `${l.action}${l.option_type}${l.strike}x${l.lots}@${l.premium}`).join("|")],
    enabled: !!chain && priced.length > 0,
    queryFn: () =>
      apiJson<ServerPayoff>("/api/analysis/payoff", {
        method: "POST",
        body: JSON.stringify({ underlying, expiry: chain?.expiry, legs: priced.map((l) => ({ action: l.action, option_type: l.option_type, strike: l.strike, lots: l.lots, premium: l.premium, iv: l.iv })) }),
      }),
  });

  const paperTrade = useMutation({
    mutationFn: async () => {
      if (!chain) return 0;
      // hedges (BUY) first for margin benefit, then shorts
      const ordered = [...priced].sort((a, b) => (a.action === b.action ? 0 : a.action === "BUY" ? -1 : 1));
      let n = 0;
      for (const l of ordered) {
        if (!l.symbol) continue;
        await unwrap(api.POST("/api/orders", { body: { symbol: l.symbol, side: l.action, quantity: l.lots * chain.lot_size, order_type: "MARKET", product: "NRML", mode: "paper" } }));
        n += 1;
      }
      return n;
    },
    onSuccess: (n) => toast.success(`Placed ${n} paper order(s)`, { action: { label: "View", onClick: () => router.push("/deployments") } }),
    onError: (e: Error) => toast.error(e.message),
  });

  const update = (i: number, patch: Partial<BLeg>) => setLegs((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Wrench}
        title="Options Strategy Builder"
        description="Compose any multi-leg position from the live chain, then what-if it by time and volatility"
        onRefresh={() => void chainQ.refetch()}
        refreshing={chainQ.isFetching}
        filters={
          <>
            <UnderlyingExpiry underlying={underlying} setUnderlying={setUnderlying} expiry={expiry} setExpiry={setExpiry} />
            <Field label="Preset">
              <Select
                value={preset}
                onValueChange={(v) => {
                  setPreset(v);
                  applyPreset(v);
                }}
                options={Object.entries(PRESETS).map(([k, p]) => ({ value: k, label: p.label }))}
              />
            </Field>
            <div className="ml-auto flex gap-2 self-end">
              <Button variant="outline" size="sm" disabled={!chain || priced.length === 0} onClick={() => chain && sendDraftToBuilder(optionsDraft(chain.underlying, priced, chain.atm_strike, step, `${chain.underlying} ${PRESETS[preset]?.label ?? "custom"}`), router.push)}>
                <Hammer /> Backtest in Builder
              </Button>
              <Button size="sm" disabled={!chain || priced.length === 0} loading={paperTrade.isPending} onClick={() => confirm(`Place ${priced.length} paper order(s) at market?`) && paperTrade.mutate()}>
                <FlaskConical /> Paper-trade basket
              </Button>
            </div>
          </>
        }
        csv={chain ? { filename: `${underlying}-builder-legs`, rows: () => priced.map(({ manualPremium: _m, ...l }) => ({ ...l, lot_size: chain.lot_size })) } : undefined}
        ask={chain ? { question: "Review this options position: what's the thesis, max risk, and what would you adjust?", context: () => ({ underlying, spot: chain.spot, expiry: chain.expiry, lot_size: chain.lot_size, legs: priced, server: server.data }) } : undefined}
      />
      {!chain ? (
        <Skeleton className="h-[600px]" />
      ) : (
        <div className="grid gap-3 xl:grid-cols-5">
          <Card className="xl:col-span-2">
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Legs · spot {num(chain.spot)} · lot {chain.lot_size}</CardTitle>
              <Button size="sm" variant="outline" disabled={legs.length >= 12} onClick={() => setLegs((ls) => [...ls, price({ action: "BUY", option_type: "CE", strike: chain.atm_strike, lots: 1, premium: 0, iv: 15 })])}>
                <Plus /> Add leg
              </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {priced.length === 0 && <EmptyState title="No legs" description="Pick a preset or add legs." />}
              {priced.map((l, i) => (
                <div key={i} className="grid grid-cols-[auto_80px_1fr_64px_84px_auto] items-end gap-1.5 rounded-md border p-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className={cn("w-14", l.action === "BUY" ? "border-profit/40 text-profit" : "border-loss/40 text-loss")}
                    onClick={() => update(i, { action: l.action === "BUY" ? "SELL" : "BUY" })}
                    aria-label={`Toggle side, currently ${l.action}`}
                  >
                    {l.action}
                  </Button>
                  <Select value={l.option_type} onValueChange={(v) => update(i, { option_type: v as "CE" | "PE", manualPremium: false })} options={[{ value: "CE", label: "CE" }, { value: "PE", label: "PE" }]} ariaLabel="Option type" />
                  <Select
                    value={String(l.strike)}
                    onValueChange={(v) => update(i, { strike: Number(v), manualPremium: false })}
                    options={strikes.map((k) => ({ value: String(k), label: `${num(k, 0)}${k === chain.atm_strike ? " (ATM)" : ""}` }))}
                    ariaLabel="Strike"
                  />
                  <Input type="number" min={1} max={100} value={l.lots} onChange={(e) => update(i, { lots: Math.max(1, Number(e.target.value)) })} aria-label="Lots" />
                  <Input
                    type="number"
                    step={0.05}
                    value={l.premium}
                    onChange={(e) => update(i, { premium: Number(e.target.value), manualPremium: true })}
                    aria-label="Premium"
                    className={cn(l.manualPremium && "border-warning")}
                    title={l.manualPremium ? "Manual premium (live LTP overridden)" : `Live LTP · IV ${num(l.iv, 1)}%`}
                  />
                  <Button size="icon-sm" variant="ghost" onClick={() => setLegs((ls) => ls.filter((_, j) => j !== i))} aria-label="Remove leg">
                    <Trash2 />
                  </Button>
                </div>
              ))}
              {server.data && (
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="Delta" value={num(server.data.greeks.delta, 1)} />
                  <Stat label="Gamma" value={num(server.data.greeks.gamma, 3)} />
                  <Stat label="Theta ₹/d" value={num(server.data.greeks.theta, 0)} tone={server.data.greeks.theta >= 0 ? "profit" : "loss"} />
                  <Stat label="Vega ₹" value={num(server.data.greeks.vega, 0)} />
                </div>
              )}
              <p className="text-2xs text-muted-foreground">
                Premiums follow the live chain; edit one to override (highlighted). Margin estimate (SPAN+exposure) is approximate: ~
                {inr(priced.filter((l) => l.action === "SELL").reduce((a, l) => a + l.strike * l.lots * chain.lot_size * 0.12, 0) * (priced.some((l) => l.action === "BUY") ? 0.35 : 1), { compact: true })}.
              </p>
            </CardContent>
          </Card>
          <div className="flex flex-col gap-3 xl:col-span-3">
            {priced.length > 0 && <PayoffPanel title="Payoff (expiry & T+n)" spot={chain.spot} legs={priced} lotSize={chain.lot_size} daysToExpiry={dte} pop={server.data?.pop ?? null} />}
            <Disclaimer kind="options" />
          </div>
        </div>
      )}
    </div>
  );
}
