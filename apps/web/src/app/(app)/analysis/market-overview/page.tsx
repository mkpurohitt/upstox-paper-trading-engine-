"use client";
import type { Schemas } from "@algo/api-client";
import { useQuery } from "@tanstack/react-query";
import { Globe2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { axisProps, tooltipStyle } from "@/components/charts/theme";
import { Pnl, SectionTitle } from "@/components/common";
import { DashboardHeader } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { useTicks } from "@/hooks/use-realtime";
import { api, unwrap } from "@/lib/api";
import { compactNum, num, pct, sym } from "@/lib/format";
import { cn, pnlClass } from "@/lib/utils";

type Overview = Schemas["OverviewOut"];
type Row = Schemas["MoverRow"];

function heat(change: number): string {
  const c = Math.max(-3, Math.min(3, change)) / 3;
  const a = 0.12 + Math.abs(c) * 0.6;
  return c >= 0 ? `hsl(var(--profit) / ${a})` : `hsl(var(--loss) / ${a})`;
}

function IndexCards({ rows }: { rows: Row[] }) {
  const live = useTicks(rows.map((r) => r.symbol));
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {rows.map((r) => {
        const t = live[r.symbol];
        const ltp = t?.ltp ?? r.ltp;
        const ch = t?.change_pct ?? r.change_pct ?? 0;
        return (
          <Link key={r.symbol} href={`/analysis/technical?symbol=${encodeURIComponent(r.symbol)}`} className="rounded-lg border bg-card p-3 transition-colors hover:border-primary/40">
            <div className="truncate text-2xs font-medium uppercase tracking-wide text-muted-foreground">{r.name ?? sym(r.symbol)}</div>
            <div className="num mt-1 text-base font-semibold">{num(ltp)}</div>
            <div className={cn("num text-xs", pnlClass(ch))}>
              {ch >= 0 ? "▲" : "▼"} {pct(ch)}
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function SectorHeatmap({ sectors }: { sectors: Overview["sectors"] }) {
  const total = sectors.reduce((a, s) => a + s.mcap_cr, 0);
  return (
    <div className="flex flex-wrap gap-1" role="list" aria-label="Sector heatmap">
      {sectors.map((s) => (
        <div
          key={s.sector}
          role="listitem"
          className="flex min-w-[140px] flex-col gap-1 rounded-md border p-1.5"
          style={{ flexGrow: Math.max(1, Math.round((s.mcap_cr / total) * 100)), flexBasis: 0 }}
        >
          <div className="flex items-center justify-between gap-2 px-1">
            <span className="truncate text-2xs font-semibold">{s.sector}</span>
            <span className={cn("num text-2xs font-medium", pnlClass(s.change_pct))}>{pct(s.change_pct)}</span>
          </div>
          <div className="flex flex-wrap gap-0.5">
            {s.stocks.map((st) => (
              <Tooltip key={st.symbol} content={`${st.name} · ${num(st.ltp)} · ${pct(st.change_pct)}`}>
                <Link
                  href={`/analysis/technical?symbol=${encodeURIComponent(st.symbol)}`}
                  className="flex min-w-[64px] flex-1 flex-col items-center justify-center rounded px-1 py-1.5 text-center"
                  style={{ background: heat(st.change_pct ?? 0), flexGrow: Math.max(1, Math.round(st.mcap_cr / 50000)) }}
                >
                  <span className="text-2xs font-semibold leading-none">{sym(st.symbol)}</span>
                  <span className="num mt-0.5 text-[10px] leading-none">{pct(st.change_pct, 1)}</span>
                </Link>
              </Tooltip>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Breadth({ b }: { b: Overview["breadth"] }) {
  const total = b.advances + b.declines + b.unchanged || 1;
  const nse = b.nse as { advances?: number; declines?: number; unchanged?: number };
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 flex justify-between text-xs">
          <span className="text-profit">Advances {b.advances}</span>
          <span className="text-muted-foreground">Unch. {b.unchanged}</span>
          <span className="text-loss">Declines {b.declines}</span>
        </div>
        <div className="flex h-2 overflow-hidden rounded-full bg-muted" aria-label="Advance decline ratio">
          <div className="bg-profit" style={{ width: `${(b.advances / total) * 100}%` }} />
          <div className="bg-muted-foreground/30" style={{ width: `${(b.unchanged / total) * 100}%` }} />
          <div className="bg-loss" style={{ width: `${(b.declines / total) * 100}%` }} />
        </div>
        <p className="mt-1 text-2xs text-muted-foreground">Tracked universe ({b.universe} large caps) · A/D ratio {(b.advances / Math.max(1, b.declines)).toFixed(2)}</p>
      </div>
      {nse.advances !== undefined && (
        <p className="text-2xs text-muted-foreground">
          NSE-wide: <span className="text-profit">{nse.advances}</span> adv / <span className="text-loss">{nse.declines}</span> dec / {nse.unchanged} unch
        </p>
      )}
    </div>
  );
}

function FiiDii({ data }: { data: Record<string, unknown> }) {
  const rows = ((data.rows as { date: string; fii_net: number; dii_net: number }[]) ?? []).slice().reverse();
  return (
    <div className="h-56">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ left: -10, right: 4, top: 8 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
          <XAxis dataKey="date" {...axisProps} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis {...axisProps} tickFormatter={(v: number) => compactNum(v)} />
          <RTooltip {...tooltipStyle} formatter={(v: number, n: string) => [`₹${num(v, 0)} Cr`, n === "fii_net" ? "FII net" : "DII net"]} />
          <ReferenceLine y={0} stroke="hsl(var(--border))" />
          <Bar dataKey="fii_net" name="fii_net" radius={[3, 3, 0, 0]}>
            {rows.map((r) => (
              <Cell key={r.date} fill={r.fii_net >= 0 ? "hsl(var(--profit))" : "hsl(var(--loss))"} />
            ))}
          </Bar>
          <Bar dataKey="dii_net" name="dii_net" fill="hsl(var(--info))" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function MoversTable({ rows, oi = false }: { rows: Row[]; oi?: boolean }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Symbol</TH>
          <TH className="text-right">LTP</TH>
          <TH className="text-right">Chg %</TH>
          {oi ? <TH className="text-right">OI Δ%</TH> : <TH className="text-right">Value (Cr)</TH>}
          {oi && <TH>Buildup</TH>}
        </TR>
      </THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.symbol}>
            <TD>
              <Link href={`/analysis/technical?symbol=${encodeURIComponent(r.symbol)}`} className="font-medium hover:text-primary">
                {sym(r.symbol)}
              </Link>
            </TD>
            <TD className="text-right">{num(r.ltp)}</TD>
            <TD className="text-right">
              <Pnl value={r.change_pct} kind="pct" />
            </TD>
            {oi ? (
              <TD className="text-right">
                <Pnl value={r.oi_change_pct} kind="pct" />
              </TD>
            ) : (
              <TD className="text-right">{num(r.value_cr, 0)}</TD>
            )}
            {oi && (
              <TD>
                <Badge variant={r.buildup?.startsWith("Long b") || r.buildup?.startsWith("Short c") ? "profit" : "loss"}>{r.buildup}</Badge>
              </TD>
            )}
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export default function MarketOverviewPage() {
  const q = useQuery({
    queryKey: ["overview"],
    queryFn: () => unwrap(api.GET("/api/market/overview")),
    refetchInterval: 15_000,
  });
  const d = q.data;
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Globe2}
        title="Market Overview"
        description="Indices, sectors, breadth, institutional flows and derivatives activity · auto-refresh 15s"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        csv={d ? { filename: "market-overview", rows: () => [...d.top_gainers, ...d.top_losers, ...d.most_active] as unknown as Record<string, unknown>[] } : undefined}
        ask={
          d
            ? {
                question: "Summarise today's market: breadth, sector rotation, FII/DII flows and notable OI activity.",
                context: () => ({ indices: d.indices, breadth: d.breadth, sectors: d.sectors.map((s) => ({ sector: s.sector, change_pct: s.change_pct })), gainers: d.top_gainers.slice(0, 5), losers: d.top_losers.slice(0, 5), oi: d.oi_gainers.slice(0, 5), fii_dii: (d.fii_dii.rows as unknown[])?.slice(0, 5) }),
              }
            : undefined
        }
      />
      {!d ? (
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-72" />
          <div className="grid gap-3 lg:grid-cols-2">
            <Skeleton className="h-64" />
            <Skeleton className="h-64" />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <IndexCards rows={d.indices} />
          <Card>
            <CardHeader>
              <CardTitle>Sector heatmap</CardTitle>
            </CardHeader>
            <CardContent>
              <SectorHeatmap sectors={d.sectors} />
            </CardContent>
          </Card>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Advance / Decline</CardTitle>
              </CardHeader>
              <CardContent>
                <Breadth b={d.breadth} />
                <SectionTitle>Sector indices</SectionTitle>
                <div className="grid grid-cols-2 gap-1.5">
                  {d.sector_indices.map((s) => (
                    <div key={s.symbol} className="flex items-center justify-between rounded-md bg-muted/40 px-2 py-1 text-xs">
                      <span className="truncate">{s.name?.replace("Nifty ", "")}</span>
                      <Pnl value={s.change_pct} kind="pct" />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>FII / DII net flows (₹ Cr, cash)</CardTitle>
              </CardHeader>
              <CardContent>
                <FiiDii data={d.fii_dii} />
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-4">
                <Tabs defaultValue="gainers">
                  <TabsList>
                    <TabsTrigger value="gainers">Top gainers</TabsTrigger>
                    <TabsTrigger value="losers">Top losers</TabsTrigger>
                    <TabsTrigger value="active">Most active</TabsTrigger>
                  </TabsList>
                  <TabsContent value="gainers">
                    <MoversTable rows={d.top_gainers} />
                  </TabsContent>
                  <TabsContent value="losers">
                    <MoversTable rows={d.top_losers} />
                  </TabsContent>
                  <TabsContent value="active">
                    <MoversTable rows={d.most_active} />
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <Tabs defaultValue="oi-up">
                  <TabsList>
                    <TabsTrigger value="oi-up">OI gainers</TabsTrigger>
                    <TabsTrigger value="oi-down">OI losers</TabsTrigger>
                  </TabsList>
                  <TabsContent value="oi-up">
                    <MoversTable rows={d.oi_gainers} oi />
                  </TabsContent>
                  <TabsContent value="oi-down">
                    <MoversTable rows={d.oi_losers} oi />
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
