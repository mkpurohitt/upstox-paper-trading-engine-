"use client";
import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows } from "lucide-react";
import * as React from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { axisProps, SERIES, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiJson } from "@/lib/api";
import { num, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Resp {
  a: string;
  b: string;
  engle_granger: { t_stat: number; p_value: number; crit_values: Record<string, number>; cointegrated_5pct: boolean };
  johansen: { trace_stat: number[]; trace_crit_95: number[]; max_eig_stat: number[]; max_eig_crit_95: number[]; rank_95: number } | null;
  hedge_ratio: number;
  spread_adf_p: number;
  half_life_days: number | null;
  correlation: number;
  current_z: number | null;
  signal: string;
  entry_z: number;
  exit_z: number;
  lookback: number;
  series: { ts: string; a: number; b: number; spread: number; z: number | null }[];
}
interface ScanRow { a: string; b: string; p_value: number; correlation: number; hedge_ratio?: number; half_life_days?: number | null }

const SECTORS = ["Financial Services", "Information Technology", "FMCG", "Automobile", "Metals & Mining", "Healthcare", "Consumer Services", "Oil Gas & Consumable Fuels", "Capital Goods"];
const short = (s: string) => s.split(":")[1] ?? s;

function Picker({ label, value, onChange }: { label: string; value: string; onChange: (s: string) => void }) {
  return (
    <Field label={label} className="min-w-[200px]">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="h-9 shrink-0 px-2 font-mono text-xs">
          {value}
        </Badge>
        <SymbolSearch onPick={onChange} placeholder="Change…" className="w-32" filter={(h) => h.instrument_type === "EQ"} />
      </div>
    </Field>
  );
}

export default function PairsPage() {
  const [a, setA] = React.useState("NSE:HDFCBANK");
  const [b, setB] = React.useState("NSE:ICICIBANK");
  const [lookback, setLookback] = React.useState("60");
  const [days, setDays] = React.useState("730");
  const [sector, setSector] = React.useState("Financial Services");
  const q = useQuery({
    queryKey: ["pairs", a, b, lookback, days],
    queryFn: () => apiJson<Resp>(`/api/analysis/pairs?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&lookback=${lookback}&days=${days}`),
  });
  const scan = useQuery({ queryKey: ["pairs-scan", sector], queryFn: () => apiJson<ScanRow[]>(`/api/analysis/pairs/scan?sector=${encodeURIComponent(sector)}`), staleTime: 300_000 });
  const d = q.data;
  const series = React.useMemo(() => (d?.series ?? []).map((p) => ({ ...p, t: shortDate(p.ts) })), [d]);
  const norm = React.useMemo(() => {
    const s = d?.series ?? [];
    const a0 = s[0]?.a ?? 1;
    const b0 = s[0]?.b ?? 1;
    return s.map((p) => ({ t: shortDate(p.ts), a: (p.a / a0) * 100, b: (p.b / b0) * 100 }));
  }, [d]);
  const zTone = d?.current_z == null ? "default" : Math.abs(d.current_z) >= d.entry_z ? "warning" : "default";
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={GitCompareArrows}
        title="Pairs Trading"
        description="Cointegration (Engle–Granger, Johansen), hedge ratio, half-life and spread z-score signals"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <Picker label="Leg A (long when z < −entry)" value={a} onChange={setA} />
            <Picker label="Leg B" value={b} onChange={setB} />
            <Field label="Z lookback">
              <Select value={lookback} onValueChange={setLookback} options={["20", "40", "60", "90", "120"].map((v) => ({ value: v, label: `${v}D` }))} />
            </Field>
            <Field label="History">
              <Select value={days} onValueChange={setDays} options={[["365", "1Y"], ["730", "2Y"], ["1095", "3Y"]].map(([v, l]) => ({ value: v!, label: l! }))} />
            </Field>
          </>
        }
        csv={d ? { filename: `pair-${short(a)}-${short(b)}`, rows: () => d.series } : undefined}
        ask={d ? { question: `Is ${short(a)}/${short(b)} a statistically sound pair right now? Explain cointegration, half-life and the current z-score signal.`, context: () => ({ ...d, series: d.series.slice(-15) }) } : undefined}
      />
      {!d ? (
        <Skeleton className="h-[640px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="Current z" value={num(d.current_z, 2)} tone={zTone} hint={`entry ±${d.entry_z} · exit ±${d.exit_z}`} />
            <Stat label="Signal" value={<span className="text-sm">{d.signal}</span>} />
            <Stat label="EG p-value" value={num(d.engle_granger.p_value, 3)} tone={d.engle_granger.cointegrated_5pct ? "profit" : "warning"} hint={d.engle_granger.cointegrated_5pct ? "cointegrated @5%" : "not cointegrated @5%"} />
            <Stat label="Johansen rank" value={d.johansen?.rank_95 ?? "—"} hint="@95%" />
            <Stat label="Spread ADF p" value={num(d.spread_adf_p, 3)} tone={d.spread_adf_p < 0.05 ? "profit" : "default"} />
            <Stat label="Hedge ratio β" value={num(d.hedge_ratio, 3)} hint={`A − β·B (log)`} />
            <Stat label="Half-life" value={d.half_life_days ? `${num(d.half_life_days, 1)}d` : "—"} />
            <Stat label="Correlation" value={num(d.correlation, 2)} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Spread z-score ({d.lookback}D rolling)</CardTitle>
              <CardDescription>Shaded bands mark entry (±{d.entry_z}) and exit (±{d.exit_z}) thresholds.</CardDescription>
            </CardHeader>
            <CardContent className="h-72">
              <ResponsiveContainer>
                <LineChart data={series} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" {...axisProps} minTickGap={50} />
                  <YAxis {...axisProps} width={32} domain={[-4, 4]} allowDataOverflow />
                  <RTooltip {...tooltipStyle} formatter={(v: number) => num(v, 2)} />
                  <ReferenceArea y1={d.entry_z} y2={4} fill="hsl(var(--loss) / 0.08)" />
                  <ReferenceArea y1={-4} y2={-d.entry_z} fill="hsl(var(--profit) / 0.08)" />
                  <ReferenceArea y1={-d.exit_z} y2={d.exit_z} fill="hsl(var(--muted-foreground) / 0.06)" />
                  <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" />
                  <ReferenceLine y={d.entry_z} stroke="hsl(var(--loss))" strokeDasharray="4 3" />
                  <ReferenceLine y={-d.entry_z} stroke="hsl(var(--profit))" strokeDasharray="4 3" />
                  <Line dataKey="z" stroke="hsl(var(--primary))" dot={false} strokeWidth={1.8} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Normalised prices (start = 100)</CardTitle>
              </CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer>
                  <LineChart data={norm} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="t" {...axisProps} minTickGap={50} />
                    <YAxis {...axisProps} width={36} domain={["auto", "auto"]} />
                    <RTooltip {...tooltipStyle} formatter={(v: number) => num(v, 1)} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line dataKey="a" name={short(d.a)} stroke={SERIES[0]} dot={false} strokeWidth={1.8} isAnimationActive={false} />
                    <Line dataKey="b" name={short(d.b)} stroke={SERIES[2]} dot={false} strokeWidth={1.8} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex-row items-center justify-between gap-2">
                <CardTitle>Pair scanner</CardTitle>
                <Select value={sector} onValueChange={setSector} options={SECTORS.map((s) => ({ value: s, label: s }))} className="h-8 w-44 text-xs" ariaLabel="Sector" />
              </CardHeader>
              <CardContent className="max-h-64 overflow-auto p-0 scrollbar-thin">
                {scan.isLoading ? (
                  <Skeleton className="m-3 h-40" />
                ) : (
                  <Table>
                    <THead>
                      <TR>
                        <TH>Pair</TH>
                        <TH className="text-right">EG p</TH>
                        <TH className="text-right">Corr</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {(scan.data ?? []).map((r) => (
                        <TR
                          key={`${r.a}-${r.b}`}
                          className={cn("cursor-pointer", r.a === a && r.b === b && "bg-primary/10")}
                          onClick={() => {
                            setA(r.a);
                            setB(r.b);
                          }}
                        >
                          <TD className="text-xs font-medium">
                            {short(r.a)} / {short(r.b)}
                          </TD>
                          <TD className={cn("num text-right text-xs", r.p_value < 0.05 ? "text-profit" : "text-muted-foreground")}>{num(r.p_value, 3)}</TD>
                          <TD className="num text-right text-xs">{num(r.correlation, 2)}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
          <p className="text-2xs text-muted-foreground">
            Cointegration can break down (mergers, regulatory shocks, regime change). Re-test regularly; a low p-value in-sample is not a guarantee of mean reversion out-of-sample.
          </p>
          <Disclaimer />
        </div>
      )}
    </div>
  );
}
