"use client";
import { useQuery } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { UnderlyingExpiry } from "@/components/analysis/pickers";
import { axisProps, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton, Switch } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiJson } from "@/lib/api";
import { compactNum, num, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Leg { symbol: string; ltp: number; oi: number; oi_change: number; iv: number | null; volume: number; greeks: { delta: number; gamma: number; theta: number; vega: number } }
interface Row { strike: number; call: Leg | null; put: Leg | null; pcr: number | null }
interface Strike { strike: number; call_oi: number; put_oi: number; call_oi_change: number; put_oi_change: number; call_iv: number | null; put_iv: number | null; call_buildup: string | null; put_buildup: string | null }
interface Resp {
  chain: { underlying: string; spot: number; expiry: string; lot_size: number; atm_strike: number; rows: Row[]; pcr: number | null; max_pain: number | null; total_call_oi: number; total_put_oi: number };
  analytics: { atm_iv: number | null; atm_straddle: number | null; expected_move: number | null; expected_range: number[] | null; days_to_expiry: number; resistance: number[]; support: number[]; oi_change_pcr: number; strikes: Strike[] };
}

const BUILDUP: Record<string, "profit" | "loss" | "info" | "warning"> = { "Long buildup": "profit", "Short buildup": "loss", "Short covering": "info", "Long unwinding": "warning" };

function OiBar({ value, max, side }: { value: number; max: number; side: "call" | "put" }) {
  return (
    <div className={cn("absolute inset-y-1 rounded-sm", side === "call" ? "right-0 bg-loss/15" : "left-0 bg-profit/15")} style={{ width: `${Math.min(100, (value / (max || 1)) * 100)}%` }} />
  );
}

export default function OptionChainPage() {
  const [underlying, setUnderlying] = React.useState("NIFTY");
  const [expiry, setExpiry] = React.useState<string | undefined>(undefined);
  const [strikes, setStrikes] = React.useState("15");
  const [greeks, setGreeks] = React.useState(false);
  const q = useQuery({
    queryKey: ["chain", underlying, expiry, strikes],
    queryFn: () => apiJson<Resp>(`/api/analysis/option-chain?underlying=${underlying}&strikes=${strikes}${expiry ? `&expiry=${expiry}` : ""}`),
    refetchInterval: 5000,
  });
  const d = q.data;
  const maxOi = d ? Math.max(...d.chain.rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0])) : 1;
  const strikesData = d?.analytics.strikes ?? [];
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Layers}
        title="Option Chain"
        description="Live chain with OI, ΔOI, IV, Greeks, PCR, max pain, IV skew and OI buildup · refresh 5s"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <UnderlyingExpiry underlying={underlying} setUnderlying={setUnderlying} expiry={expiry} setExpiry={setExpiry} />
            <Field label="Strikes ±">
              <Select value={strikes} onValueChange={setStrikes} options={["8", "10", "15", "20", "30"].map((s) => ({ value: s, label: s }))} />
            </Field>
            <label className="flex h-9 items-center gap-2 self-end text-xs">
              <Switch checked={greeks} onCheckedChange={setGreeks} /> Greeks
            </label>
          </>
        }
        csv={d ? { filename: `${underlying}-chain-${d.chain.expiry}`, rows: () => d.chain.rows.map((r) => ({ strike: r.strike, call_ltp: r.call?.ltp, call_oi: r.call?.oi, call_oi_change: r.call?.oi_change, call_iv: r.call?.iv, call_delta: r.call?.greeks.delta, put_ltp: r.put?.ltp, put_oi: r.put?.oi, put_oi_change: r.put?.oi_change, put_iv: r.put?.iv, put_delta: r.put?.greeks.delta, pcr: r.pcr })) } : undefined}
        ask={d ? { question: `Interpret the ${underlying} option chain: PCR, max pain, OI support/resistance, IV skew and expected range.`, context: () => ({ underlying, spot: d.chain.spot, expiry: d.chain.expiry, pcr: d.chain.pcr, max_pain: d.chain.max_pain, ...d.analytics, strikes: undefined }) } : undefined}
      />
      {!d ? (
        <Skeleton className="h-[600px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="Spot" value={num(d.chain.spot)} />
            <Stat label="PCR (OI)" value={num(d.chain.pcr, 2)} tone={(d.chain.pcr ?? 1) > 1 ? "profit" : "loss"} hint={`ΔOI PCR ${num(d.analytics.oi_change_pcr, 2)}`} />
            <Stat label="Max pain" value={num(d.chain.max_pain, 0)} />
            <Stat label="ATM IV" value={d.analytics.atm_iv ? `${num(d.analytics.atm_iv)}%` : "—"} />
            <Stat label="ATM straddle" value={num(d.analytics.atm_straddle)} />
            <Stat label="Expected range" value={d.analytics.expected_range ? `${num(d.analytics.expected_range[0], 0)}–${num(d.analytics.expected_range[1], 0)}` : "—"} hint="±1σ to expiry" />
            <Stat label="Days to expiry" value={num(d.analytics.days_to_expiry, 1)} hint={shortDate(d.chain.expiry)} />
            <Stat label="Lot size" value={d.chain.lot_size} hint={`R ${d.analytics.resistance.join(", ")} · S ${d.analytics.support.join(", ")}`} />
          </div>
          <Tabs defaultValue="chain">
            <TabsList>
              <TabsTrigger value="chain">Chain</TabsTrigger>
              <TabsTrigger value="oi">OI & ΔOI</TabsTrigger>
              <TabsTrigger value="skew">IV skew</TabsTrigger>
              <TabsTrigger value="buildup">OI buildup</TabsTrigger>
            </TabsList>
            <TabsContent value="chain">
              <Card>
                <CardContent className="overflow-x-auto p-0 scrollbar-thin">
                  <table className="w-full min-w-[900px] text-xs num">
                    <thead className="sticky top-0 bg-card text-2xs uppercase text-muted-foreground">
                      <tr className="border-b">
                        {greeks && <th className="px-2 py-2 text-right">Δ</th>}
                        <th className="px-2 py-2 text-right">OI</th>
                        <th className="px-2 py-2 text-right">ΔOI</th>
                        <th className="px-2 py-2 text-right">Vol</th>
                        <th className="px-2 py-2 text-right">IV</th>
                        <th className="px-2 py-2 text-right text-loss">Call LTP</th>
                        <th className="bg-muted/40 px-2 py-2 text-center">Strike</th>
                        <th className="px-2 py-2 text-left text-profit">Put LTP</th>
                        <th className="px-2 py-2 text-left">IV</th>
                        <th className="px-2 py-2 text-left">Vol</th>
                        <th className="px-2 py-2 text-left">ΔOI</th>
                        <th className="px-2 py-2 text-left">OI</th>
                        {greeks && <th className="px-2 py-2 text-left">Δ</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {d.chain.rows.map((r) => {
                        const itmCall = r.strike < d.chain.spot;
                        const atm = r.strike === d.chain.atm_strike;
                        return (
                          <tr key={r.strike} className={cn("border-b", atm && "border-y-2 border-y-primary/50")}>
                            {greeks && <td className={cn("px-2 py-1 text-right", itmCall && "bg-warning/5")}>{num(r.call?.greeks.delta, 2)}</td>}
                            <td className={cn("relative px-2 py-1 text-right", itmCall && "bg-warning/5")}>
                              <OiBar value={r.call?.oi ?? 0} max={maxOi} side="call" />
                              <span className="relative">{compactNum(r.call?.oi)}</span>
                            </td>
                            <td className={cn("px-2 py-1 text-right", (r.call?.oi_change ?? 0) >= 0 ? "text-profit" : "text-loss", itmCall && "bg-warning/5")}>{compactNum(r.call?.oi_change)}</td>
                            <td className={cn("px-2 py-1 text-right text-muted-foreground", itmCall && "bg-warning/5")}>{compactNum(r.call?.volume)}</td>
                            <td className={cn("px-2 py-1 text-right", itmCall && "bg-warning/5")}>{num(r.call?.iv, 1)}</td>
                            <td className={cn("px-2 py-1 text-right font-medium", itmCall && "bg-warning/5")}>{num(r.call?.ltp)}</td>
                            <td className={cn("bg-muted/40 px-2 py-1 text-center font-semibold", atm && "text-primary")}>{num(r.strike, 0)}</td>
                            <td className={cn("px-2 py-1 font-medium", !itmCall && "bg-warning/5")}>{num(r.put?.ltp)}</td>
                            <td className={cn("px-2 py-1", !itmCall && "bg-warning/5")}>{num(r.put?.iv, 1)}</td>
                            <td className={cn("px-2 py-1 text-muted-foreground", !itmCall && "bg-warning/5")}>{compactNum(r.put?.volume)}</td>
                            <td className={cn("px-2 py-1", (r.put?.oi_change ?? 0) >= 0 ? "text-profit" : "text-loss", !itmCall && "bg-warning/5")}>{compactNum(r.put?.oi_change)}</td>
                            <td className={cn("relative px-2 py-1", !itmCall && "bg-warning/5")}>
                              <OiBar value={r.put?.oi ?? 0} max={maxOi} side="put" />
                              <span className="relative">{compactNum(r.put?.oi)}</span>
                            </td>
                            {greeks && <td className={cn("px-2 py-1", !itmCall && "bg-warning/5")}>{num(r.put?.greeks.delta, 2)}</td>}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="oi">
              <div className="grid gap-3 lg:grid-cols-2">
                {(["oi", "change"] as const).map((k) => (
                  <Card key={k}>
                    <CardHeader>
                      <CardTitle>{k === "oi" ? "Open interest by strike" : "Change in OI by strike"}</CardTitle>
                    </CardHeader>
                    <CardContent className="h-72">
                      <ResponsiveContainer>
                        <BarChart data={strikesData} margin={{ left: 0, right: 8 }}>
                          <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                          <XAxis dataKey="strike" {...axisProps} />
                          <YAxis {...axisProps} width={48} tickFormatter={(v: number) => compactNum(v)} />
                          <RTooltip {...tooltipStyle} formatter={(v: number) => compactNum(v)} />
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <ReferenceLine x={d.chain.atm_strike} stroke="hsl(var(--primary))" strokeDasharray="3 3" />
                          <Bar dataKey={k === "oi" ? "call_oi" : "call_oi_change"} name="Calls" fill="hsl(var(--loss))" radius={[2, 2, 0, 0]} />
                          <Bar dataKey={k === "oi" ? "put_oi" : "put_oi_change"} name="Puts" fill="hsl(var(--profit))" radius={[2, 2, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </TabsContent>
            <TabsContent value="skew">
              <Card>
                <CardHeader>
                  <CardTitle>Implied volatility smile / skew</CardTitle>
                </CardHeader>
                <CardContent className="h-80">
                  <ResponsiveContainer>
                    <LineChart data={strikesData} margin={{ left: 0, right: 8 }}>
                      <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
                      <XAxis dataKey="strike" {...axisProps} />
                      <YAxis {...axisProps} width={40} domain={["auto", "auto"]} unit="%" />
                      <RTooltip {...tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <ReferenceLine x={d.chain.atm_strike} stroke="hsl(var(--primary))" strokeDasharray="3 3" />
                      <Line dataKey="call_iv" name="Call IV" stroke="hsl(var(--loss))" dot={false} strokeWidth={2} />
                      <Line dataKey="put_iv" name="Put IV" stroke="hsl(var(--profit))" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="buildup">
              <Card>
                <CardContent className="grid gap-1 pt-4 sm:grid-cols-2">
                  {strikesData.map((s) => (
                    <div key={s.strike} className="flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-xs">
                      <Badge variant={BUILDUP[s.call_buildup ?? ""] ?? "secondary"}>CE {s.call_buildup}</Badge>
                      <span className="num font-semibold">{num(s.strike, 0)}</span>
                      <Badge variant={BUILDUP[s.put_buildup ?? ""] ?? "secondary"}>PE {s.put_buildup}</Badge>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
          <Disclaimer kind="options" />
        </div>
      )}
    </div>
  );
}
