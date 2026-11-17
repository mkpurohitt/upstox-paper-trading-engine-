"use client";
import { useQuery } from "@tanstack/react-query";
import { Building2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { SERIES, axisProps, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, EmptyState, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, apiJson } from "@/lib/api";
import { compactNum, croreInr, inr, num, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Ratios { pe: number; pb: number; roe_pct: number; roce_pct: number; debt_to_equity: number; dividend_yield_pct: number; net_margin_pct: number; revenue_growth_3y_pct: number; eps_ttm: number; book_value: number; market_cap_cr: number; face_value: number }
interface Resp {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  price: number | null;
  ratios: Ratios;
  annual: { fy: string; revenue_cr: number; ebitda_cr: number; pat_cr: number; eps: number }[];
  quarterly: { quarter: string; revenue_cr: number; pat_cr: number }[];
  source: string;
  peers: ({ symbol: string; name: string; market_cap_cr: number } & Partial<Ratios>)[];
  shareholding: { as_of: string; promoter: number; fii: number; dii: number; public: number; pledged_pct_of_promoter: number; source: string };
  corporate_actions: { purpose: string; ex_date: string; record_date: string }[];
}

const PEER_COLS: [keyof Ratios, string, number][] = [
  ["market_cap_cr", "M-cap (₹Cr)", 0],
  ["pe", "P/E", 1],
  ["pb", "P/B", 2],
  ["roe_pct", "ROE %", 1],
  ["debt_to_equity", "D/E", 2],
  ["net_margin_pct", "Net margin %", 1],
  ["dividend_yield_pct", "Div yield %", 2],
];

function Inner() {
  const params = useSearchParams();
  const [symbol, setSymbol] = React.useState(params.get("symbol") ?? "NSE:RELIANCE");
  const [period, setPeriod] = React.useState<"annual" | "quarterly">("annual");
  const q = useQuery({
    queryKey: ["fundamentals", symbol],
    queryFn: () => apiJson<Resp>(`/api/analysis/fundamentals?symbol=${encodeURIComponent(symbol)}`),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
  const d = q.data;
  const share = d ? [
    { name: "Promoter", value: d.shareholding.promoter },
    { name: "FII", value: d.shareholding.fii },
    { name: "DII", value: d.shareholding.dii },
    { name: "Public", value: d.shareholding.public },
  ] : [];
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Building2}
        title="Fundamental Analysis"
        description="Valuation and quality ratios, financial trends, peer comparison, shareholding and corporate actions"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <Field label="Company" className="min-w-[260px]">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="h-9 shrink-0 px-2 font-mono text-xs">
                {symbol}
              </Badge>
              <SymbolSearch onPick={setSymbol} placeholder="Search equity…" className="w-48" filter={(h) => h.instrument_type === "EQ"} />
            </div>
          </Field>
        }
        csv={d ? { filename: `${symbol.replace(":", "_")}-financials`, rows: () => (period === "annual" ? d.annual : d.quarterly) } : undefined}
        ask={d ? { question: `Summarise ${d.name}'s fundamentals: valuation vs peers, growth, profitability, balance sheet and ownership.`, context: () => d } : undefined}
      />
      {q.isError ? (
        <EmptyState title="No fundamentals" description={(q.error as Error).message} />
      ) : !d ? (
        <Skeleton className="h-[600px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">{d.name}</h2>
            <Badge variant="secondary">{d.sector}</Badge>
            <Badge variant="outline">{d.industry}</Badge>
            {d.price ? <span className="num text-sm">{inr(d.price)}</span> : null}
            {d.source === "mock" && <Badge variant="warning">sample data — connect a fundamentals provider for live figures</Badge>}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="Market cap" value={croreInr(d.ratios.market_cap_cr)} />
            <Stat label="P/E" value={num(d.ratios.pe, 1)} hint={`EPS ${num(d.ratios.eps_ttm)}`} />
            <Stat label="P/B" value={num(d.ratios.pb, 2)} hint={`BV ${num(d.ratios.book_value)}`} />
            <Stat label="ROE" value={`${num(d.ratios.roe_pct, 1)}%`} tone={d.ratios.roe_pct >= 15 ? "profit" : "default"} />
            <Stat label="ROCE" value={`${num(d.ratios.roce_pct, 1)}%`} />
            <Stat label="Debt / equity" value={num(d.ratios.debt_to_equity, 2)} tone={d.ratios.debt_to_equity > 1.5 ? "warning" : "default"} />
            <Stat label="Net margin" value={`${num(d.ratios.net_margin_pct, 1)}%`} />
            <Stat label="Div. yield" value={`${num(d.ratios.dividend_yield_pct, 2)}%`} hint={`3Y rev CAGR ${num(d.ratios.revenue_growth_3y_pct, 1)}%`} />
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle>Financials (₹ Cr)</CardTitle>
                <Tabs value={period} onValueChange={(v) => setPeriod(v as "annual" | "quarterly")}>
                  <TabsList>
                    <TabsTrigger value="annual">Annual</TabsTrigger>
                    <TabsTrigger value="quarterly">Quarterly</TabsTrigger>
                  </TabsList>
                </Tabs>
              </CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer>
                  <BarChart data={period === "annual" ? d.annual : d.quarterly} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey={period === "annual" ? "fy" : "quarter"} {...axisProps} />
                    <YAxis {...axisProps} width={56} tickFormatter={(v: number) => compactNum(v)} />
                    <RTooltip {...tooltipStyle} formatter={(v: number) => `₹${compactNum(v)} Cr`} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="revenue_cr" name="Revenue" fill={SERIES[1]} radius={[3, 3, 0, 0]} />
                    {period === "annual" && <Bar dataKey="ebitda_cr" name="EBITDA" fill={SERIES[0]} radius={[3, 3, 0, 0]} />}
                    <Bar dataKey="pat_cr" name="Net profit" fill={SERIES[3]} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Shareholding</CardTitle>
                <CardDescription>
                  as of {shortDate(d.shareholding.as_of)} · pledged {num(d.shareholding.pledged_pct_of_promoter, 1)}% of promoter
                </CardDescription>
              </CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={share} dataKey="value" nameKey="name" innerRadius={50} outerRadius={85} paddingAngle={2} stroke="hsl(var(--card))">
                      {share.map((_, i) => (
                        <Cell key={i} fill={SERIES[i % SERIES.length]} />
                      ))}
                    </Pie>
                    <RTooltip {...tooltipStyle} formatter={(v: number) => `${v}%`} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Peer comparison · {d.sector}</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <THead>
                    <TR>
                      <TH>Company</TH>
                      {PEER_COLS.map(([, l]) => (
                        <TH key={l} className="text-right">
                          {l}
                        </TH>
                      ))}
                    </TR>
                  </THead>
                  <TBody>
                    {d.peers.map((p) => (
                      <TR key={p.symbol} className={cn(p.symbol === d.symbol && "bg-primary/10")}>
                        <TD>
                          <button type="button" className="text-left text-xs font-medium hover:text-primary" onClick={() => setSymbol(p.symbol)}>
                            {p.name}
                          </button>
                        </TD>
                        {PEER_COLS.map(([k, l, dg]) => (
                          <TD key={l} className="num text-right text-xs">
                            {k === "market_cap_cr" ? compactNum(p[k]) : num(p[k], dg)}
                          </TD>
                        ))}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Corporate actions</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {d.corporate_actions.length === 0 && <p className="text-xs text-muted-foreground">No upcoming actions.</p>}
                {d.corporate_actions.map((a, i) => (
                  <div key={i} className="rounded-md border p-2 text-xs">
                    <div className="font-medium">{a.purpose}</div>
                    <div className="text-2xs text-muted-foreground">
                      Ex-date {shortDate(a.ex_date)} · record {shortDate(a.record_date)}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
          <Disclaimer />
        </div>
      )}
    </div>
  );
}

export default function FundamentalPage() {
  return (
    <React.Suspense>
      <Inner />
    </React.Suspense>
  );
}
