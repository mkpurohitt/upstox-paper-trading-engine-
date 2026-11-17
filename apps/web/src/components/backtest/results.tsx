"use client";
import type { Schemas } from "@algo/api-client";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AlertTriangle } from "lucide-react";
import * as React from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { axisProps, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, Pnl, SectionTitle, Stat } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, unwrap } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { compactInr, compactNum, inr, istTime, num, pct, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type Backtest = Schemas["BacktestOut"];
type M = Record<string, number | null | undefined>;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function tone(v: number | null | undefined, good = 0): "profit" | "loss" | "default" {
  if (v === null || v === undefined) return "default";
  return v > good ? "profit" : v < good ? "loss" : "default";
}

export function MetricsGrid({ m }: { m: M }) {
  const items: [string, React.ReactNode, ReturnType<typeof tone>, string?][] = [
    ["Net P&L", inr(m.net_pnl, { signed: true, decimals: 0 }), tone(m.net_pnl), `${pct(m.total_return_pct)} total`],
    ["CAGR", pct(m.cagr_pct), tone(m.cagr_pct), m.benchmark_return_pct !== undefined ? `B&H ${pct(m.benchmark_return_pct)}` : undefined],
    ["Sharpe", num(m.sharpe), tone(m.sharpe, 1), "rf 6.5%"],
    ["Sortino", num(m.sortino), tone(m.sortino, 1)],
    ["Calmar", num(m.calmar), tone(m.calmar, 0.5)],
    ["Max drawdown", pct(m.max_drawdown_pct), "loss", `${m.max_drawdown_days ?? 0} days underwater`],
    ["Win rate", pct(m.win_rate_pct, 1, false), tone((m.win_rate_pct ?? 0) - 50), `${m.trades ?? 0} trades`],
    ["Profit factor", num(m.profit_factor), tone(m.profit_factor, 1)],
    ["Expectancy", inr(m.expectancy, { decimals: 0 }), tone(m.expectancy), "per trade"],
    ["Avg win / loss", `${compactInr(m.avg_win ?? 0)} / ${compactInr(m.avg_loss ?? 0)}`, "default", `payoff ${num(m.payoff_ratio)}`],
    ["Charges", inr(m.total_charges, { decimals: 0 }), "default", m.charges_pct_of_gross ? `${num(m.charges_pct_of_gross, 1)}% of gross` : undefined],
    ["Exposure", pct(m.exposure_pct, 1, false), "default", `avg ${num(m.avg_bars_held, 1)} bars held`],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      {items.map(([label, value, t, hint]) => (
        <Stat key={label} label={label} value={value} tone={t} hint={hint} />
      ))}
    </div>
  );
}

export function EquityCharts({ bt }: { bt: Pick<Backtest, "equity_curve" | "drawdown_curve" | "extra"> }) {
  const bench = (bt.extra?.benchmark_curve as { ts: string; value: number }[] | null) ?? [];
  const bmap = new Map(bench.map((p) => [p.ts.slice(0, 10), p.value]));
  const data = bt.equity_curve.map((p) => ({ ts: p.ts as string, equity: p.value as number, bench: bmap.get(String(p.ts).slice(0, 10)) }));
  const dd = bt.drawdown_curve.map((p) => ({ ts: p.ts as string, dd: p.value as number }));
  return (
    <div className="flex flex-col gap-1">
      <div className="h-64">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <defs>
              <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
            <XAxis dataKey="ts" {...axisProps} tickFormatter={(t: string) => shortDate(t)} minTickGap={40} />
            <YAxis {...axisProps} width={64} tickFormatter={(v: number) => compactNum(v)} domain={["auto", "auto"]} />
            <RTooltip {...tooltipStyle} labelFormatter={(t) => istTime(String(t), true)} formatter={(v: number, n: string) => [inr(v, { decimals: 0 }), n === "equity" ? "Strategy" : "Buy & hold"]} />
            <Area type="monotone" dataKey="equity" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#eq)" dot={false} isAnimationActive={false} />
            {bench.length > 0 && <Line type="monotone" dataKey="bench" stroke="hsl(var(--muted-foreground))" strokeDasharray="4 3" strokeWidth={1} dot={false} connectNulls isAnimationActive={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="h-28">
        <ResponsiveContainer>
          <AreaChart data={dd} margin={{ left: 0, right: 8 }}>
            <XAxis dataKey="ts" hide />
            <YAxis {...axisProps} width={64} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <RTooltip {...tooltipStyle} labelFormatter={(t) => istTime(String(t), true)} formatter={(v: number) => [`${v.toFixed(2)}%`, "Drawdown"]} />
            <Area type="monotone" dataKey="dd" stroke="hsl(var(--loss))" fill="hsl(var(--loss) / 0.25)" dot={false} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function MonthlyHeatmap({ rows }: { rows: { year: number; month: number; return_pct: number }[] }) {
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const get = (y: number, m: number) => rows.find((r) => r.year === y && r.month === m)?.return_pct;
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.return_pct)));
  if (!rows.length) return <p className="text-xs text-muted-foreground">Not enough history for monthly returns.</p>;
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full border-separate border-spacing-0.5 text-2xs num">
        <thead>
          <tr>
            <th className="w-12 text-left font-medium text-muted-foreground">Year</th>
            {MONTHS.map((m) => (
              <th key={m} className="font-medium text-muted-foreground">
                {m}
              </th>
            ))}
            <th className="font-medium text-muted-foreground">Year</th>
          </tr>
        </thead>
        <tbody>
          {years.map((y) => {
            const total = rows.filter((r) => r.year === y).reduce((a, r) => a * (1 + r.return_pct / 100), 1);
            return (
              <tr key={y}>
                <td className="font-medium">{y}</td>
                {MONTHS.map((_, i) => {
                  const v = get(y, i + 1);
                  const a = v === undefined ? 0 : 0.15 + (Math.abs(v) / max) * 0.65;
                  return (
                    <td key={i} className="h-7 rounded text-center" style={{ background: v === undefined ? "transparent" : v >= 0 ? `hsl(var(--profit) / ${a})` : `hsl(var(--loss) / ${a})` }} title={v === undefined ? "" : `${MONTHS[i]} ${y}: ${v.toFixed(2)}%`}>
                      {v === undefined ? "" : v.toFixed(1)}
                    </td>
                  );
                })}
                <td className={cn("text-center font-semibold", total >= 1 ? "text-profit" : "text-loss")}>{((total - 1) * 100).toFixed(1)}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function DowChart({ rows }: { rows: { day: string; net_pnl: number; trades: number; win_rate_pct: number }[] }) {
  return (
    <div className="h-48">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
          <XAxis dataKey="day" {...axisProps} />
          <YAxis {...axisProps} width={56} tickFormatter={(v: number) => compactNum(v)} />
          <RTooltip {...tooltipStyle} formatter={(v: number, _n, p) => [`${inr(v, { decimals: 0 })} · ${(p.payload as { trades: number }).trades} trades · ${(p.payload as { win_rate_pct: number }).win_rate_pct}% wins`, "Net P&L"]} />
          <ReferenceLine y={0} stroke="hsl(var(--border))" />
          <Bar dataKey="net_pnl" radius={[3, 3, 0, 0]}>
            {rows.map((r) => (
              <Cell key={r.day} fill={r.net_pnl >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MonteCarloChart({ mc }: { mc: Record<string, unknown> }) {
  const bands = mc.bands as Record<string, number[]>;
  const data = (bands.p50 ?? []).map((_, i) => ({ i, band: [bands.p5?.[i], bands.p95?.[i]], iqr: [bands.p25?.[i], bands.p75?.[i]], p50: bands.p50?.[i] }));
  const fe = mc.final_equity as Record<string, number>;
  const dd = mc.max_drawdown_pct as Record<string, number>;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Median final equity" value={compactInr(fe.p50 ?? 0)} hint={`5–95%: ${compactInr(fe.p5 ?? 0)} – ${compactInr(fe.p95 ?? 0)}`} />
        <Stat label="P(profit)" value={pct(Number(mc.probability_of_profit) * 100, 1, false)} tone={Number(mc.probability_of_profit) > 0.5 ? "profit" : "loss"} />
        <Stat label="Risk of ruin" value={pct(Number(mc.risk_of_ruin) * 100, 1, false)} tone={Number(mc.risk_of_ruin) > 0.05 ? "loss" : "profit"} hint={`equity < ${100 - Number(mc.ruin_threshold_pct)}% of start`} />
        <Stat label="95th pct drawdown" value={pct(dd.p95, 1)} tone="loss" hint={`median ${pct(dd.p50, 1)}`} />
      </div>
      <div className="h-56">
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <XAxis dataKey="i" {...axisProps} tickFormatter={(v: number) => `#${v}`} />
            <YAxis {...axisProps} width={64} tickFormatter={(v: number) => compactNum(v)} domain={["auto", "auto"]} />
            <RTooltip {...tooltipStyle} formatter={(v: unknown) => (Array.isArray(v) ? `${compactInr(v[0])} – ${compactInr(v[1])}` : compactInr(Number(v)))} labelFormatter={(l) => `after trade ${l}`} />
            <Area dataKey="band" stroke="none" fill="hsl(var(--primary) / 0.12)" isAnimationActive={false} />
            <Area dataKey="iqr" stroke="none" fill="hsl(var(--primary) / 0.22)" isAnimationActive={false} />
            <Area dataKey="p50" stroke="hsl(var(--primary))" fill="none" strokeWidth={2} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-2xs text-muted-foreground">{String(mc.runs)} {String(mc.method)} resamples of {String(mc.trades)} trades. Shaded: 5–95% and 25–75% bands.</p>
    </div>
  );
}

function TradesTable({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["bt-trades", id], queryFn: () => unwrap(api.GET("/api/backtests/{backtest_id}/trades", { params: { path: { backtest_id: id }, query: { limit: 5000 } } })) });
  const parent = React.useRef<HTMLDivElement>(null);
  const rows = q.data ?? [];
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 32, overscan: 12 });
  if (q.isLoading) return <Skeleton className="h-64" />;
  const cols = "grid grid-cols-[1.4fr_0.7fr_0.6fr_1.2fr_0.8fr_1.2fr_0.8fr_0.9fr_0.8fr_1fr] items-center gap-2 px-2";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end">
        <Button variant="outline" size="xs" onClick={() => downloadCsv(`backtest-${id}-trades`, rows as unknown as Record<string, unknown>[], ["symbol", "leg", "side", "quantity", "entry_ts", "entry_price", "exit_ts", "exit_price", "gross_pnl", "charges", "net_pnl", "exit_reason"])}>
          Export CSV
        </Button>
      </div>
      <div className={cn(cols, "h-8 rounded-t-md bg-muted/50 text-2xs font-medium uppercase text-muted-foreground")}>
        <span>Symbol</span>
        <span>Side</span>
        <span className="text-right">Qty</span>
        <span>Entry</span>
        <span className="text-right">Price</span>
        <span>Exit</span>
        <span className="text-right">Price</span>
        <span className="text-right">Charges</span>
        <span className="text-right">Net</span>
        <span>Reason</span>
      </div>
      <div ref={parent} className="h-[420px] overflow-auto scrollbar-thin" role="table" aria-label="Trade log">
        <div style={{ height: v.getTotalSize(), position: "relative" }}>
          {v.getVirtualItems().map((it) => {
            const t = rows[it.index]!;
            return (
              <div key={t.id} role="row" className={cn(cols, "absolute inset-x-0 border-b text-xs num")} style={{ top: it.start, height: it.size }}>
                <span className="truncate font-medium" title={t.symbol}>
                  {t.leg ? `${t.leg} · ` : ""}
                  {t.symbol}
                </span>
                <Badge variant={t.side.startsWith("LONG") ? "profit" : t.side.startsWith("SHORT") ? "loss" : "secondary"}>{t.side}</Badge>
                <span className="text-right">{t.quantity}</span>
                <span className="truncate text-muted-foreground">{istTime(t.entry_ts, true)}</span>
                <span className="text-right">{num(t.entry_price)}</span>
                <span className="truncate text-muted-foreground">{t.exit_ts ? istTime(t.exit_ts, true) : "—"}</span>
                <span className="text-right">{num(t.exit_price)}</span>
                <span className="text-right text-muted-foreground">{num(t.charges, 0)}</span>
                <Pnl value={t.net_pnl} className="text-right" />
                <span className="truncate text-muted-foreground">{t.exit_reason?.replace(/_/g, " ")}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function BacktestResults({ bt }: { bt: Backtest }) {
  const m = bt.metrics as M;
  const extra = bt.extra ?? {};
  const warnings = (extra.warnings as string[]) ?? [];
  const charges = (extra.charges_breakdown as Record<string, number>) ?? {};
  const reasons = (extra.exit_reasons as Record<string, number>) ?? {};
  const mc = extra.monte_carlo as Record<string, unknown> | undefined;
  return (
    <div className="flex flex-col gap-3">
      {warnings.length > 0 && (
        <div className="flex flex-col gap-1 rounded-lg border border-warning/30 bg-warning/5 p-2 text-xs">
          {warnings.map((w, i) => (
            <p key={i} className="flex items-start gap-1.5 text-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w}
            </p>
          ))}
        </div>
      )}
      <MetricsGrid m={m} />
      <Tabs defaultValue="equity">
        <TabsList>
          <TabsTrigger value="equity">Equity & drawdown</TabsTrigger>
          <TabsTrigger value="monthly">Monthly</TabsTrigger>
          <TabsTrigger value="trades">Trades ({m.trades ?? 0})</TabsTrigger>
          <TabsTrigger value="costs">Costs & exits</TabsTrigger>
          {mc && <TabsTrigger value="mc">Monte Carlo</TabsTrigger>}
        </TabsList>
        <TabsContent value="equity">
          <Card>
            <CardContent className="pt-4">
              <EquityCharts bt={bt} />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="monthly">
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Monthly returns</CardTitle>
              </CardHeader>
              <CardContent>
                <MonthlyHeatmap rows={bt.monthly_returns as { year: number; month: number; return_pct: number }[]} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Day-of-week P&L</CardTitle>
              </CardHeader>
              <CardContent>
                <DowChart rows={(extra.dow_stats as { day: string; net_pnl: number; trades: number; win_rate_pct: number }[]) ?? []} />
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="trades">
          <TradesTable id={bt.id} />
        </TabsContent>
        <TabsContent value="costs">
          <div className="grid gap-3 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Charges breakdown</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 text-sm">
                {Object.entries(charges).map(([k, v]) => (
                  <div key={k} className={cn("flex justify-between", k === "total" && "border-t pt-1.5 font-semibold")}>
                    <span className="capitalize text-muted-foreground">{k === "stt" ? "STT / CTT" : k === "ipft" ? "IPFT" : k === "gst" ? "GST (18%)" : k}</span>
                    <span className="num">{inr(v)}</span>
                  </div>
                ))}
                <p className="pt-2 text-2xs text-muted-foreground">Broker plan: {String((bt.params as Record<string, unknown>).broker)} · slippage {String((bt.params as Record<string, unknown>).slippage_bps)} bps</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Exit reasons</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {Object.entries(reasons).map(([k, v]) => (
                  <Badge key={k} variant="secondary" className="text-xs">
                    {k.replace(/_/g, " ")} · {v}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        {mc && (
          <TabsContent value="mc">
            <Card>
              <CardContent className="pt-4">
                <MonteCarloChart mc={mc} />
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
      <SectionTitle>Notes</SectionTitle>
      <Disclaimer kind="trading" />
      <p className="text-2xs text-muted-foreground">
        Data source: {String(extra.data_source ?? "—")} · runtime {String(extra.runtime_s ?? "—")}s · {String((bt.params as Record<string, unknown>).mode)} engine · fills at {String((bt.params as Record<string, unknown>).fill).replace("_", " ")}
      </p>
    </div>
  );
}
