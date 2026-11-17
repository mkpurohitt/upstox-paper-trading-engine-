"use client";
import { useQuery } from "@tanstack/react-query";
import { Sigma } from "lucide-react";
import * as React from "react";
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { axisProps, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { SymbolMultiPicker, SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { apiJson } from "@/lib/api";
import { num, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Resp {
  symbol: string;
  benchmark: string;
  observations: number;
  stats: { mean_daily_pct: number; ann_return_pct: number; ann_vol_pct: number; skew: number; excess_kurtosis: number; var95_pct: number; var99_pct: number; cvar95_pct: number; jarque_bera_p: number; beta: number | null; current_vol_pct: number; current_regime: string };
  histogram: { bin: number; count: number; normal: number }[];
  vol_regimes: { ts: string; vol: number; regime: string }[];
  regime_thresholds: { low: number; high: number };
  rolling_beta: { ts: string; beta: number }[];
  correlation: { symbols: string[]; matrix: (number | null)[][] };
  seasonality_month: { month: string; mean_pct: number; hit_rate_pct: number; years: number }[];
  seasonality_dow: { day: string; mean_pct: number; count: number }[];
}

/** Diverging blue–white–red scale for correlations (colour-blind safe: blue/orange-red). */
function corrColor(v: number | null): string {
  if (v === null) return "transparent";
  const a = Math.min(1, Math.abs(v));
  return v >= 0 ? `rgba(61,155,245,${0.12 + a * 0.75})` : `rgba(245,115,36,${0.12 + a * 0.75})`;
}
const short = (s: string) => s.split(":")[1] ?? s;

export default function QuantPage() {
  const [symbol, setSymbol] = React.useState("NSE:HDFCBANK");
  const [basket, setBasket] = React.useState<string[]>(["NSE:ICICIBANK", "NSE:SBIN", "NSE:KOTAKBANK", "NSE:AXISBANK"]);
  const [benchmark, setBenchmark] = React.useState("NSE_INDEX:NIFTY");
  const [days, setDays] = React.useState("1095");
  const q = useQuery({
    queryKey: ["quant", symbol, basket, benchmark, days],
    queryFn: () => apiJson<Resp>(`/api/analysis/quant?symbol=${encodeURIComponent(symbol)}&basket=${encodeURIComponent(basket.join(","))}&benchmark=${encodeURIComponent(benchmark)}&days=${days}`),
  });
  const d = q.data;
  const vol = React.useMemo(() => {
    const rows = d?.vol_regimes ?? [];
    // a point belongs to its own regime and the previous one, so coloured segments join up at transitions
    const on = (i: number, r: string) => rows[i]?.regime === r || rows[i - 1]?.regime === r;
    return rows.map((p, i) => ({ ...p, t: shortDate(p.ts), low: on(i, "low") ? p.vol : null, mid: on(i, "normal") ? p.vol : null, high: on(i, "high") ? p.vol : null }));
  }, [d]);
  const beta = React.useMemo(() => (d?.rolling_beta ?? []).map((p) => ({ ...p, t: shortDate(p.ts) })), [d]);
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Sigma}
        title="Quant Analysis"
        description="Return distribution, tail risk, volatility regimes, rolling beta, correlations and seasonality"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <Field label="Symbol" className="min-w-[220px]">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="h-9 shrink-0 px-2 font-mono text-xs">
                  {symbol}
                </Badge>
                <SymbolSearch onPick={setSymbol} placeholder="Change…" className="w-36" />
              </div>
            </Field>
            <Field label="Correlation basket" className="min-w-[260px] flex-1">
              <SymbolMultiPicker value={basket} onChange={(v) => setBasket(v.slice(0, 11))} />
            </Field>
            <Field label="Benchmark">
              <Select value={benchmark} onValueChange={setBenchmark} options={["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "NSE_INDEX:FINNIFTY", "NSE_INDEX:NIFTYIT", "NSE_INDEX:MIDCPNIFTY"].map((b) => ({ value: b, label: short(b) }))} />
            </Field>
            <Field label="History">
              <Select value={days} onValueChange={setDays} options={[["365", "1Y"], ["1095", "3Y"], ["1825", "5Y"]].map(([v, l]) => ({ value: v!, label: l! }))} />
            </Field>
          </>
        }
        csv={d ? { filename: `${short(symbol)}-quant`, rows: () => d.vol_regimes.map((v, i) => ({ ts: v.ts, vol: v.vol, regime: v.regime, rolling_beta: d.rolling_beta[i - (d.vol_regimes.length - d.rolling_beta.length)]?.beta ?? null })) } : undefined}
        ask={d ? { question: `Interpret the risk profile of ${symbol}: fat tails, VaR, volatility regime, beta and diversification with the basket.`, context: () => ({ symbol, benchmark, stats: d.stats, correlation: d.correlation, seasonality_month: d.seasonality_month }) } : undefined}
      />
      {!d ? (
        <Skeleton className="h-[700px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="Ann. return" value={`${num(d.stats.ann_return_pct, 1)}%`} tone={d.stats.ann_return_pct >= 0 ? "profit" : "loss"} hint={`${d.observations} days`} />
            <Stat label="Ann. volatility" value={`${num(d.stats.ann_vol_pct, 1)}%`} hint={`now ${num(d.stats.current_vol_pct, 1)}%`} />
            <Stat label="Regime" value={d.stats.current_regime} tone={d.stats.current_regime === "high" ? "warning" : "default"} />
            <Stat label="Beta" value={num(d.stats.beta, 2)} hint={`vs ${short(d.benchmark)}`} />
            <Stat label="VaR 95% (1d)" value={`${num(d.stats.var95_pct, 2)}%`} tone="loss" hint={`99%: ${num(d.stats.var99_pct, 2)}%`} />
            <Stat label="CVaR 95%" value={`${num(d.stats.cvar95_pct, 2)}%`} tone="loss" />
            <Stat label="Skew" value={num(d.stats.skew, 2)} hint={d.stats.skew < 0 ? "left tail heavier" : "right tail heavier"} />
            <Stat label="Excess kurtosis" value={num(d.stats.excess_kurtosis, 2)} hint={`JB p=${num(d.stats.jarque_bera_p, 3)} ${d.stats.jarque_bera_p < 0.05 ? "(non-normal)" : ""}`} />
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Daily return distribution vs normal</CardTitle>
              </CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer>
                  <ComposedChart data={d.histogram} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="bin" {...axisProps} tickFormatter={(v: number) => `${num(v, 1)}%`} />
                    <YAxis {...axisProps} width={36} />
                    <RTooltip {...tooltipStyle} labelFormatter={(v) => `${num(Number(v), 2)}%`} />
                    <ReferenceLine x={d.histogram.reduce((b, h) => (Math.abs(h.bin - d.stats.var95_pct) < Math.abs(b - d.stats.var95_pct) ? h.bin : b), 0)} stroke="hsl(var(--loss))" strokeDasharray="4 3" label={{ value: "VaR95", fill: "hsl(var(--loss))", fontSize: 10, position: "top" }} />
                    <Bar dataKey="count" name="Observed" fill="hsl(var(--info) / 0.6)" radius={[2, 2, 0, 0]} />
                    <Line dataKey="normal" name="Normal fit" stroke="hsl(var(--warning))" strokeWidth={2} dot={false} type="monotone" />
                  </ComposedChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Volatility regimes (20D realised, annualised)</CardTitle>
                <CardDescription>
                  low &lt; {num(d.regime_thresholds.low, 1)}% · high &gt; {num(d.regime_thresholds.high, 1)}%
                </CardDescription>
              </CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer>
                  <ComposedChart data={vol} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="t" {...axisProps} minTickGap={50} />
                    <YAxis {...axisProps} width={36} unit="%" />
                    <RTooltip {...tooltipStyle} />
                    <ReferenceLine y={d.regime_thresholds.low} stroke="hsl(var(--profit))" strokeDasharray="3 3" />
                    <ReferenceLine y={d.regime_thresholds.high} stroke="hsl(var(--loss))" strokeDasharray="3 3" />
                    <Area dataKey="vol" stroke="none" fill="hsl(var(--muted-foreground) / 0.08)" isAnimationActive={false} />
                    <Line dataKey="low" name="Low" stroke="hsl(var(--profit))" dot={false} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
                    <Line dataKey="mid" name="Normal" stroke="hsl(var(--info))" dot={false} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
                    <Line dataKey="high" name="High" stroke="hsl(var(--loss))" dot={false} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Correlation matrix (daily returns)</CardTitle>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="mx-auto text-2xs num" role="grid" aria-label="Correlation matrix">
                  <thead>
                    <tr>
                      <th />
                      {d.correlation.symbols.map((s) => (
                        <th key={s} className="px-1 pb-1 font-medium text-muted-foreground [writing-mode:vertical-rl]">
                          {short(s)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {d.correlation.matrix.map((row, i) => (
                      <tr key={i}>
                        <th className="pr-2 text-right font-medium text-muted-foreground">{short(d.correlation.symbols[i] ?? "")}</th>
                        {row.map((v, j) => (
                          <td key={j} className="h-9 w-9 text-center" style={{ background: corrColor(v) }} title={`${short(d.correlation.symbols[i] ?? "")} × ${short(d.correlation.symbols[j] ?? "")}: ${num(v, 2)}`}>
                            {num(v, 2)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Rolling 60D beta vs {short(d.benchmark)}</CardTitle>
              </CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer>
                  <LineChart data={beta} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="t" {...axisProps} minTickGap={50} />
                    <YAxis {...axisProps} width={36} domain={["auto", "auto"]} />
                    <RTooltip {...tooltipStyle} formatter={(v: number) => num(v, 2)} />
                    <ReferenceLine y={1} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
                    <Line dataKey="beta" stroke="hsl(var(--primary))" dot={false} strokeWidth={2} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Monthly seasonality</CardTitle>
                <CardDescription>Average return by calendar month (hit rates — share of positive years — are listed alongside)</CardDescription>
              </CardHeader>
              <CardContent className="h-60">
                <ResponsiveContainer>
                  <BarChart data={d.seasonality_month} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="month" {...axisProps} />
                    <YAxis {...axisProps} width={36} unit="%" />
                    <RTooltip {...tooltipStyle} formatter={(v: number) => `${num(v, 2)}%`} />
                    <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" />
                    <Bar dataKey="mean_pct" name="Mean return" radius={[3, 3, 0, 0]}>
                      {d.seasonality_month.map((m) => (
                        <Cell key={m.month} fill={m.mean_pct >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Day-of-week effect</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 pt-2">
                {d.seasonality_dow.map((r) => (
                  <div key={r.day} className="flex items-center gap-2 text-xs">
                    <span className="w-9 font-medium">{r.day}</span>
                    <div className="relative h-4 flex-1 rounded bg-muted/50">
                      <div
                        className={cn("absolute inset-y-0 rounded", r.mean_pct >= 0 ? "left-1/2 bg-profit/60" : "right-1/2 bg-loss/60")}
                        style={{ width: `${Math.min(50, (Math.abs(r.mean_pct) / Math.max(...d.seasonality_dow.map((x) => Math.abs(x.mean_pct)), 0.01)) * 50)}%` }}
                      />
                    </div>
                    <span className={cn("num w-14 text-right", r.mean_pct >= 0 ? "text-profit" : "text-loss")}>
                      {r.mean_pct >= 0 ? "+" : ""}
                      {num(r.mean_pct, 3)}%
                    </span>
                  </div>
                ))}
                <div className="mt-2 grid grid-cols-3 gap-1 text-2xs">
                  {d.seasonality_month.map((m) => (
                    <span key={m.month} className="text-muted-foreground">
                      {m.month}: <span className={m.hit_rate_pct >= 50 ? "text-profit" : "text-loss"}>{num(m.hit_rate_pct, 0)}%</span>
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
          <Disclaimer />
        </div>
      )}
    </div>
  );
}
