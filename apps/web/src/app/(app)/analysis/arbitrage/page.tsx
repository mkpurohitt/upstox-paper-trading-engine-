"use client";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import * as React from "react";
import { Disclaimer, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton, Switch } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiJson } from "@/lib/api";
import { istTime, num, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface CashFut { symbol: string; spot: number; future: number; expiry: string; basis: number; basis_pct: number; annualised_pct: number; net_annualised_pct: number; days: number; lot_size: number; signal: string }
interface Calendar { symbol: string; near: number; far: number; spread: number; fair_spread: number; mispricing: number; mispricing_pct: number }
interface NseBse { symbol: string; nse: number; bse: number; diff: number; diff_bps: number; actionable: boolean }
interface Pcp { underlying: string; strike: number; call: number; put: number; c_minus_p: number; s_minus_pv_k: number; deviation: number; violation: boolean; trade: string }
interface Resp { ts: string; cost_bps: number; cash_futures: CashFut[]; calendar: Calendar[]; nse_bse: NseBse[]; put_call_parity: Pcp[]; note: string }

type Tab = "cash_futures" | "calendar" | "nse_bse" | "put_call_parity";
const SIGNAL: Record<string, "profit" | "loss" | "secondary"> = { "cash & carry": "profit", "reverse c&c": "loss", fair: "secondary" };

export default function ArbitragePage() {
  const [cost, setCost] = React.useState(6);
  const [auto, setAuto] = React.useState(true);
  const [onlyActionable, setOnlyActionable] = React.useState(false);
  const [tab, setTab] = React.useState<Tab>("cash_futures");
  const q = useQuery({
    queryKey: ["arbitrage", cost],
    queryFn: () => apiJson<Resp>(`/api/analysis/arbitrage?cost_bps=${cost}`),
    refetchInterval: auto ? 5000 : false,
  });
  const d = q.data;
  const cf = (d?.cash_futures ?? []).filter((r) => !onlyActionable || r.signal !== "fair");
  const cal = (d?.calendar ?? []).filter((r) => !onlyActionable || Math.abs(r.mispricing_pct) > cost / 100);
  const nb = (d?.nse_bse ?? []).filter((r) => !onlyActionable || r.actionable);
  const pcp = (d?.put_call_parity ?? []).filter((r) => !onlyActionable || r.violation);
  const current: Record<string, unknown>[] = ({ cash_futures: cf, calendar: cal, nse_bse: nb, put_call_parity: pcp }[tab] ?? []) as unknown as Record<string, unknown>[];
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={ArrowLeftRight}
        title="Arbitrage Scanner"
        description="Cash–futures basis, calendar spreads, NSE–BSE price gaps and put-call parity, net of estimated costs"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <Field label="Round-trip cost (bps)">
              <Input type="number" min={0} max={100} step={0.5} value={cost} onChange={(e) => setCost(Math.max(0, Number(e.target.value)))} className="w-28" />
            </Field>
            <label className="flex h-9 items-center gap-2 self-end text-xs">
              <Switch checked={onlyActionable} onCheckedChange={setOnlyActionable} /> Actionable only
            </label>
            <label className="flex h-9 items-center gap-2 self-end text-xs">
              <Switch checked={auto} onCheckedChange={setAuto} /> Auto-refresh 5s
            </label>
            {d && <span className="ml-auto self-end pb-2 text-2xs text-muted-foreground">as of {istTime(d.ts)} IST</span>}
          </>
        }
        csv={d ? { filename: `arbitrage-${tab}`, rows: () => current } : undefined}
        ask={d ? { question: "Which of these arbitrage opportunities look genuinely actionable after costs and execution risk, and why?", context: () => ({ tab, cost_bps: cost, rows: current.slice(0, 15) }) } : undefined}
      />
      {!d ? (
        <Skeleton className="h-[500px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Cash-carry setups" value={d.cash_futures.filter((r) => r.signal !== "fair").length} hint={`of ${d.cash_futures.length} F&O stocks`} />
            <Stat label="Best net annualised" value={`${num(Math.max(...d.cash_futures.map((r) => r.net_annualised_pct)), 2)}%`} tone="profit" />
            <Stat label="NSE–BSE actionable" value={d.nse_bse.filter((r) => r.actionable).length} />
            <Stat label="PCP violations" value={d.put_call_parity.filter((r) => r.violation).length} tone={d.put_call_parity.some((r) => r.violation) ? "warning" : "default"} />
          </div>
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
            <TabsList>
              <TabsTrigger value="cash_futures">Cash–Futures ({cf.length})</TabsTrigger>
              <TabsTrigger value="calendar">Calendar ({cal.length})</TabsTrigger>
              <TabsTrigger value="nse_bse">NSE–BSE ({nb.length})</TabsTrigger>
              <TabsTrigger value="put_call_parity">Put-call parity ({pcp.length})</TabsTrigger>
            </TabsList>
            <Card className="mt-2">
              <CardContent className="max-h-[620px] overflow-auto p-0 scrollbar-thin">
                <TabsContent value="cash_futures" className="mt-0">
                  <Table>
                    <THead>
                      <TR>
                        <TH>Symbol</TH>
                        <TH className="text-right">Spot</TH>
                        <TH className="text-right">Future</TH>
                        <TH>Expiry</TH>
                        <TH className="text-right">Basis</TH>
                        <TH className="text-right">Basis %</TH>
                        <TH className="text-right">Annualised</TH>
                        <TH className="text-right">Net of costs</TH>
                        <TH className="text-right">Lot</TH>
                        <TH>Signal</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {cf.map((r) => (
                        <TR key={r.symbol}>
                          <TD className="font-medium">{r.symbol}</TD>
                          <TD className="num text-right">{num(r.spot)}</TD>
                          <TD className="num text-right">{num(r.future)}</TD>
                          <TD className="text-muted-foreground">
                            {shortDate(r.expiry)} · {r.days}d
                          </TD>
                          <TD className={cn("num text-right", r.basis >= 0 ? "text-profit" : "text-loss")}>{num(r.basis)}</TD>
                          <TD className="num text-right">{num(r.basis_pct, 3)}%</TD>
                          <TD className="num text-right">{num(r.annualised_pct)}%</TD>
                          <TD className={cn("num text-right font-medium", r.net_annualised_pct > 0 ? "text-profit" : "text-muted-foreground")}>{num(r.net_annualised_pct)}%</TD>
                          <TD className="num text-right">{r.lot_size}</TD>
                          <TD>
                            <Badge variant={SIGNAL[r.signal] ?? "secondary"}>{r.signal}</Badge>
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </TabsContent>
                <TabsContent value="calendar" className="mt-0">
                  <Table>
                    <THead>
                      <TR>
                        <TH>Symbol</TH>
                        <TH className="text-right">Near fut</TH>
                        <TH className="text-right">Far fut</TH>
                        <TH className="text-right">Spread</TH>
                        <TH className="text-right">Fair spread (carry)</TH>
                        <TH className="text-right">Mispricing</TH>
                        <TH className="text-right">Mispricing %</TH>
                        <TH>Trade</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {cal.map((r) => (
                        <TR key={r.symbol}>
                          <TD className="font-medium">{r.symbol}</TD>
                          <TD className="num text-right">{num(r.near)}</TD>
                          <TD className="num text-right">{num(r.far)}</TD>
                          <TD className="num text-right">{num(r.spread)}</TD>
                          <TD className="num text-right">{num(r.fair_spread)}</TD>
                          <TD className={cn("num text-right", r.mispricing >= 0 ? "text-profit" : "text-loss")}>{num(r.mispricing)}</TD>
                          <TD className="num text-right">{num(r.mispricing_pct, 3)}%</TD>
                          <TD className="text-2xs text-muted-foreground">{Math.abs(r.mispricing_pct) <= cost / 100 ? "within costs" : r.mispricing > 0 ? "sell far / buy near" : "buy far / sell near"}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </TabsContent>
                <TabsContent value="nse_bse" className="mt-0">
                  <Table>
                    <THead>
                      <TR>
                        <TH>Symbol</TH>
                        <TH className="text-right">NSE</TH>
                        <TH className="text-right">BSE</TH>
                        <TH className="text-right">Diff</TH>
                        <TH className="text-right">Diff (bps)</TH>
                        <TH>Status</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {nb.map((r) => (
                        <TR key={r.symbol}>
                          <TD className="font-medium">{r.symbol}</TD>
                          <TD className="num text-right">{num(r.nse)}</TD>
                          <TD className="num text-right">{num(r.bse)}</TD>
                          <TD className={cn("num text-right", r.diff >= 0 ? "text-profit" : "text-loss")}>{num(r.diff)}</TD>
                          <TD className="num text-right">{num(r.diff_bps, 1)}</TD>
                          <TD>{r.actionable ? <Badge variant="profit">{r.diff > 0 ? "buy NSE / sell BSE" : "buy BSE / sell NSE"}</Badge> : <Badge variant="secondary">within costs</Badge>}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </TabsContent>
                <TabsContent value="put_call_parity" className="mt-0">
                  <Table>
                    <THead>
                      <TR>
                        <TH>Underlying</TH>
                        <TH className="text-right">Strike</TH>
                        <TH className="text-right">Call</TH>
                        <TH className="text-right">Put</TH>
                        <TH className="text-right">C − P</TH>
                        <TH className="text-right">S − PV(K)</TH>
                        <TH className="text-right">Deviation</TH>
                        <TH>Trade</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {pcp.map((r) => (
                        <TR key={`${r.underlying}-${r.strike}`} className={cn(r.violation && "bg-warning/5")}>
                          <TD className="font-medium">{r.underlying}</TD>
                          <TD className="num text-right">{num(r.strike, 0)}</TD>
                          <TD className="num text-right">{num(r.call)}</TD>
                          <TD className="num text-right">{num(r.put)}</TD>
                          <TD className="num text-right">{num(r.c_minus_p)}</TD>
                          <TD className="num text-right">{num(r.s_minus_pv_k)}</TD>
                          <TD className={cn("num text-right", r.violation && "font-semibold text-warning")}>{num(r.deviation)}</TD>
                          <TD className="text-2xs">{r.violation ? <Badge variant="warning">{r.trade}</Badge> : <span className="text-muted-foreground">—</span>}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </TabsContent>
              </CardContent>
            </Card>
          </Tabs>
          <Disclaimer kind="trading" />
          <p className="text-2xs text-muted-foreground">{d.note}</p>
        </div>
      )}
    </div>
  );
}
