"use client";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, Download, Layers, Link2, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { axisProps, SERIES, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, EmptyState, PageHeader, Pnl, Stat } from "@/components/common";
import { useAskAI } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiJson } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { compactInr, inr, num, pct, shortDate } from "@/lib/format";
import { cn, pnlClass } from "@/lib/utils";

type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const short = (s: string) => s.split(":").pop() ?? s;

function Allocation({ a }: { a: Any }) {
  const sectors = (a.by_sector ?? []) as Any[];
  const kinds = (a.by_instrument ?? []) as Any[];
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>By sector</CardTitle>
        </CardHeader>
        <CardContent className="h-64">
          {sectors.length === 0 ? (
            <EmptyState title="No exposure" />
          ) : (
            <ResponsiveContainer>
              <PieChart>
                <Pie data={sectors} dataKey="value" nameKey="sector" innerRadius={55} outerRadius={90} paddingAngle={2} stroke="hsl(var(--card))">
                  {sectors.map((_, i) => (
                    <Cell key={i} fill={SERIES[i % SERIES.length]} />
                  ))}
                </Pie>
                <RTooltip {...tooltipStyle} formatter={(v: number) => compactInr(v)} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Weights</CardTitle>
          <CardDescription>Share of gross exposure</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {sectors.map((s, i) => (
            <div key={s.sector} className="flex items-center gap-2 text-xs">
              <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: SERIES[i % SERIES.length] }} />
              <span className="w-36 truncate">{s.sector}</span>
              <div className="h-1.5 flex-1 rounded-full bg-muted">
                <div className="h-full rounded-full" style={{ width: `${s.weight_pct}%`, background: SERIES[i % SERIES.length] }} />
              </div>
              <span className="num w-12 text-right">{num(s.weight_pct, 1)}%</span>
            </div>
          ))}
          <div className="mt-2 flex flex-wrap gap-1">
            {kinds.map((k) => (
              <Badge key={k.kind} variant="outline" className="capitalize">
                {k.kind}: {compactInr(k.value)}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Risk</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Gross" value={compactInr(a.gross_exposure ?? 0)} />
            <Stat label="Net" value={compactInr(a.net_exposure ?? 0)} />
            <Stat label="Beta" value={num(a.portfolio_beta, 2)} />
            <Stat label="HHI" value={num(a.concentration?.hhi, 2)} hint={a.concentration?.top_symbol ? `top ${short(a.concentration.top_symbol)} ${num(a.concentration.top_weight_pct, 0)}%` : undefined} tone={(a.concentration?.hhi ?? 0) > 0.25 ? "warning" : "default"} />
          </div>
          <ul className="flex flex-col gap-1 text-xs">
            {((a.observations ?? []) as string[]).map((o, i) => (
              <li key={i} className="flex items-start gap-1.5 text-muted-foreground">
                <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0 text-warning" /> {o}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function Performance() {
  const q = useQuery({ queryKey: ["portfolio-perf"], queryFn: () => apiJson<Any>("/api/portfolio/performance?days=365") });
  const d = q.data;
  if (!d) return <Skeleton className="h-80" />;
  const daily = ((d.daily ?? []) as Any[]).map((p) => ({ ...p, t: shortDate(p.date) })) as Any[];
  const eq = ((d.equity ?? []) as Any[]).map((p) => ({ ...p, t: shortDate(p.date) }));
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="Current value" value={compactInr(d.current_value)} hint={`from ${compactInr(d.starting_capital)}`} />
        <Stat label="Total return" value={pct(d.total_return_pct)} tone={d.total_return_pct >= 0 ? "profit" : "loss"} />
        <Stat label="XIRR" value={d.xirr_pct != null ? pct(d.xirr_pct) : "—"} hint={d.xirr_pct == null ? "needs ≥ 7 days" : "money-weighted"} />
        <Stat label="Winning days" value={`${d.winning_days}/${d.trading_days}`} />
        <Stat label="Best / worst day" value={<span className="text-sm"><Pnl value={d.best_day?.realised} /> / <Pnl value={d.worst_day?.realised} /></span>} />
      </div>
      {daily.length === 0 ? (
        <EmptyState icon={Briefcase} title="No closed trades yet" description="Realised P&L appears here once paper trades are closed." />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Equity (realised, net of charges)</CardTitle>
            </CardHeader>
            <CardContent className="h-64">
              <ResponsiveContainer>
                <AreaChart data={eq} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" {...axisProps} minTickGap={40} />
                  <YAxis {...axisProps} width={60} tickFormatter={(v: number) => compactInr(v)} domain={["auto", "auto"]} />
                  <RTooltip {...tooltipStyle} formatter={(v: number) => inr(v, { decimals: 0 })} />
                  <Area dataKey="equity" stroke="hsl(var(--primary))" fill="hsl(var(--primary) / 0.12)" strokeWidth={2} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Daily realised P&amp;L</CardTitle>
            </CardHeader>
            <CardContent className="h-64">
              <ResponsiveContainer>
                <BarChart data={daily} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" {...axisProps} minTickGap={40} />
                  <YAxis {...axisProps} width={56} tickFormatter={(v: number) => compactInr(v)} />
                  <RTooltip {...tooltipStyle} formatter={(v: number) => inr(v, { decimals: 0 })} />
                  <Bar dataKey="realised" radius={[2, 2, 0, 0]}>
                    {daily.map((p, i) => (
                      <Cell key={i} fill={p.realised >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}
      <p className="text-2xs text-muted-foreground">{d.note}</p>
    </div>
  );
}

function Overlap() {
  const q = useQuery({ queryKey: ["portfolio-overlap"], queryFn: () => apiJson<Any>("/api/portfolio/overlap") });
  const d = q.data;
  if (!d) return <Skeleton className="h-40" />;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategy overlap</CardTitle>
        <CardDescription>
          {d.active_deployments} active deployment(s) across {d.instruments} instrument(s). Several strategies on the same instrument concentrate risk even when each looks small.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {(d.shared ?? []).length === 0 ? (
          <p className="text-xs text-muted-foreground">No instrument is traded by more than one active deployment.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {(d.shared as Any[]).map((s) => (
              <li key={s.instrument} className="rounded-md border p-2 text-xs">
                <span className="font-semibold">{short(s.instrument)}</span> traded by {s.deployments.length} strategies:{" "}
                {(s.deployments as Any[]).map((x) => (
                  <Link key={x.deployment_id} href={`/deployments?focus=${x.deployment_id}`} className="mr-2 text-primary underline">
                    {x.name} ({x.mode})
                  </Link>
                ))}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Dividends() {
  const q = useQuery({ queryKey: ["portfolio-dividends"], queryFn: () => apiJson<Any>("/api/portfolio/dividends") });
  const d = q.data;
  if (!d) return <Skeleton className="h-40" />;
  const items = (d.items ?? []) as Any[];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Upcoming corporate actions on your holdings</CardTitle>
        <CardDescription>Estimated dividends {inr(d.estimated_total, { decimals: 0 })} (before TDS)</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {items.length === 0 ? (
          <p className="p-4 text-xs text-muted-foreground">No announced actions for your holdings.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Stock</TH>
                <TH>Action</TH>
                <TH>Ex-date</TH>
                <TH className="text-right">Qty</TH>
                <TH className="text-right">Est. amount</TH>
              </TR>
            </THead>
            <TBody>
              {items.map((x, i) => (
                <TR key={i}>
                  <TD className="font-medium">{short(x.symbol)}</TD>
                  <TD className="text-xs">{x.purpose}</TD>
                  <TD className="text-xs">{x.ex_date ? shortDate(x.ex_date) : "—"}</TD>
                  <TD className="num text-right">{x.quantity}</TD>
                  <TD className="num text-right">{x.estimated_amount != null ? inr(x.estimated_amount, { decimals: 0 }) : "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export default function PortfolioPage() {
  const ask = useAskAI();
  const q = useQuery({ queryKey: ["portfolio"], queryFn: () => apiJson<Any>("/api/portfolio/summary"), refetchInterval: 15_000 });
  const d = q.data;
  const t = (d?.totals ?? {}) as Any;
  const holdings = (d?.holdings ?? []) as Any[];
  const positions = (d?.positions ?? []) as Any[];
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        icon={Briefcase}
        title="Portfolio"
        description="Holdings and positions across your paper account and connected brokers"
        actions={
          <>
            <Button variant="outline" size="sm" disabled={!holdings.length} onClick={() => downloadCsv("holdings", holdings)}>
              <Download /> CSV
            </Button>
            <Button
              size="sm"
              disabled={!d}
              onClick={() =>
                ask("Give me an overview of my portfolio: performance, concentration, sector risk and what to watch.", {
                  totals: t,
                  analysis: { ...d?.analysis, weights: d?.analysis?.weights?.slice(0, 10) },
                  holdings: holdings.slice(0, 15).map((h) => ({ symbol: h.symbol, qty: h.quantity, pnl_pct: h.pnl_pct, value: h.value })),
                  positions: positions.slice(0, 10),
                })
              }
            >
              <Sparkles /> AI overview
            </Button>
          </>
        }
      />
      {!d ? (
        <Skeleton className="h-[500px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Net worth" value={compactInr(t.net_worth ?? 0)} hint="all accounts" />
            <Stat label="Cash available" value={compactInr(t.cash ?? 0)} />
            <Stat label="Holdings" value={compactInr(t.holdings_value ?? 0)} hint={`invested ${compactInr(t.holdings_invested ?? 0)}`} />
            <Stat label="Holdings P&L" value={<Pnl value={t.holdings_pnl} />} hint={t.holdings_pnl_pct != null ? pct(t.holdings_pnl_pct) : undefined} />
            <Stat label="Open positions" value={<Pnl value={t.positions_unrealised} />} hint={`${positions.length} position(s)`} />
            <Stat label="Day P&L" value={<Pnl value={t.day_pnl} />} />
          </div>
          <div className="flex flex-wrap gap-2">
            {(d.accounts as Any[]).map((a) => (
              <div key={a.account} className={cn("flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs", a.error && "border-warning/40")}>
                <span className={cn("h-2 w-2 rounded-full", a.status === "connected" && !a.error ? "bg-profit" : "bg-warning")} />
                <span className="font-medium capitalize">{a.label}</span>
                {a.funds ? <span className="num text-muted-foreground">{compactInr(a.funds.total)}</span> : null}
                {a.error ? <span className="text-warning">{a.error}</span> : null}
              </div>
            ))}
            <Button asChild size="sm" variant="ghost" className="text-muted-foreground">
              <Link href="/profile?tab=brokers">
                <Link2 /> Connect a broker
              </Link>
            </Button>
          </div>
          <Tabs defaultValue="holdings">
            <TabsList>
              <TabsTrigger value="holdings">Holdings ({holdings.length})</TabsTrigger>
              <TabsTrigger value="positions">Positions ({positions.length})</TabsTrigger>
              <TabsTrigger value="allocation">Allocation & risk</TabsTrigger>
              <TabsTrigger value="performance">Performance</TabsTrigger>
              <TabsTrigger value="overlap">Overlap</TabsTrigger>
              <TabsTrigger value="dividends">Dividends</TabsTrigger>
            </TabsList>
            <TabsContent value="holdings">
              <Card>
                <CardContent className="p-0">
                  {holdings.length === 0 ? (
                    <EmptyState className="m-4" icon={Layers} title="No holdings" description="Buy with product CNC (delivery) on the Live → Paper desk, or connect a broker to see its holdings here." />
                  ) : (
                    <Table>
                      <THead>
                        <TR>
                          <TH>Stock</TH>
                          <TH>Account</TH>
                          <TH className="text-right">Qty</TH>
                          <TH className="text-right">Avg</TH>
                          <TH className="text-right">LTP</TH>
                          <TH className="text-right">Invested</TH>
                          <TH className="text-right">Value</TH>
                          <TH className="text-right">P&amp;L</TH>
                          <TH className="text-right">Weight</TH>
                        </TR>
                      </THead>
                      <TBody>
                        {holdings.map((h) => (
                          <TR key={`${h.account}-${h.symbol}`}>
                            <TD>
                              <Link href={`/analysis/fundamental?symbol=${encodeURIComponent(h.symbol)}`} className="font-medium hover:text-primary">
                                {short(h.symbol)}
                              </Link>
                              <div className="text-2xs text-muted-foreground">{h.sector ?? ""}</div>
                            </TD>
                            <TD className="text-xs capitalize text-muted-foreground">{h.account.replace("live:", "broker #")}</TD>
                            <TD className="num text-right">{h.quantity}</TD>
                            <TD className="num text-right">{num(h.average_price)}</TD>
                            <TD className="num text-right">{num(h.last_price)}</TD>
                            <TD className="num text-right">{compactInr(h.invested)}</TD>
                            <TD className="num text-right">{compactInr(h.value)}</TD>
                            <TD className={cn("num text-right", pnlClass(h.pnl))}>
                              {inr(h.pnl, { decimals: 0, signed: true })}
                              <div className="text-2xs">{pct(h.pnl_pct)}</div>
                            </TD>
                            <TD className="num text-right">{num(((h.value / (t.holdings_value || 1)) * 100), 1)}%</TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="positions">
              <Card>
                <CardContent className="p-0">
                  {positions.length === 0 ? (
                    <EmptyState className="m-4" title="No open positions" />
                  ) : (
                    <Table>
                      <THead>
                        <TR>
                          <TH>Instrument</TH>
                          <TH>Product</TH>
                          <TH className="text-right">Qty</TH>
                          <TH className="text-right">Avg</TH>
                          <TH className="text-right">LTP</TH>
                          <TH className="text-right">Unrealised</TH>
                          <TH className="text-right">Realised</TH>
                        </TR>
                      </THead>
                      <TBody>
                        {positions.map((p) => (
                          <TR key={`${p.account}-${p.symbol}-${p.product}`}>
                            <TD className="font-medium">{short(p.symbol)}</TD>
                            <TD className="text-xs">{p.product}</TD>
                            <TD className={cn("num text-right", p.quantity < 0 && "text-loss")}>{p.quantity}</TD>
                            <TD className="num text-right">{num(p.average_price)}</TD>
                            <TD className="num text-right">{num(p.last_price)}</TD>
                            <TD className="num text-right"><Pnl value={p.unrealised_pnl} /></TD>
                            <TD className="num text-right"><Pnl value={p.realised_pnl} /></TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="allocation">
              <Allocation a={d.analysis ?? {}} />
            </TabsContent>
            <TabsContent value="performance">
              <Performance />
            </TabsContent>
            <TabsContent value="overlap">
              <Overlap />
            </TabsContent>
            <TabsContent value="dividends">
              <Dividends />
            </TabsContent>
          </Tabs>
          <Disclaimer />
        </div>
      )}
    </div>
  );
}
