"use client";
import { useQuery } from "@tanstack/react-query";
import { CandlestickChart, TrendingDown, TrendingUp } from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { PriceChart, type Marker, type Overlay } from "@/components/charts/price-chart";
import { SERIES } from "@/components/charts/theme";
import { Disclaimer, EmptyState, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { useTicks } from "@/hooks/use-realtime";
import { ApiError, apiJson } from "@/lib/api";
import { num, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Series { id: string; kind: string; output: string; series: { ts: string; value: number | null }[] }
interface Trend { trend: string; score?: number; close?: number; ema20?: number; ema50?: number; rsi?: number; adx?: number; supertrend?: string }
interface Resp {
  symbol: string;
  interval: string;
  candles: { ts: string; open: number; high: number; low: number; close: number; volume: number }[];
  overlays: Series[];
  oscillators: Series[];
  patterns: { ts: string; pattern: string; bias: string; price: number }[];
  levels: { price: number; touches: number; strength: number; type: "support" | "resistance" }[];
  mtf: Record<string, Trend>;
  summary: Trend;
}

const INDICATORS = [
  { id: "EMA:20", label: "EMA 20" },
  { id: "EMA:50", label: "EMA 50" },
  { id: "SMA:200", label: "SMA 200" },
  { id: "BBANDS", label: "Bollinger" },
  { id: "SUPERTREND", label: "Supertrend" },
  { id: "VWAP", label: "VWAP" },
  { id: "DONCHIAN", label: "Donchian" },
  { id: "RSI", label: "RSI" },
  { id: "MACD", label: "MACD" },
  { id: "ADX", label: "ADX" },
  { id: "STOCH", label: "Stochastic" },
  { id: "CCI", label: "CCI" },
  { id: "ATR", label: "ATR" },
];
const HIDDEN_OUTPUTS = new Set(["width", "pct_b", "direction"]);
const INTERVALS = ["5m", "15m", "30m", "1h", "1d", "1w"];

function TrendBadge({ t }: { t: Trend }) {
  const bull = t.trend.includes("bull");
  const bear = t.trend.includes("bear");
  return (
    <Badge variant={bull ? "profit" : bear ? "loss" : "secondary"} className="gap-1">
      {bull ? <TrendingUp className="h-3 w-3" /> : bear ? <TrendingDown className="h-3 w-3" /> : null}
      {t.trend}
    </Badge>
  );
}

function Inner() {
  const params = useSearchParams();
  const [symbol, setSymbol] = React.useState(params.get("symbol") ?? "NSE:RELIANCE");
  const [interval, setInterval] = React.useState("1d");
  const [sel, setSel] = React.useState<string[]>(["EMA:20", "EMA:50", "BBANDS", "RSI", "MACD"]);
  const [showPatterns, setShowPatterns] = React.useState(true);
  const q = useQuery({
    queryKey: ["technical", symbol, interval, sel],
    queryFn: () => apiJson<Resp>(`/api/analysis/technical?symbol=${encodeURIComponent(symbol)}&interval=${interval}&indicators=${encodeURIComponent(sel.join(","))}`),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
  const ticks = useTicks([symbol]);
  const d = q.data;

  const { overlays, markers } = React.useMemo(() => {
    if (!d) return { overlays: [] as Overlay[], markers: [] as Marker[] };
    const ov: Overlay[] = [];
    let ci = 0;
    for (const o of d.overlays) {
      if (HIDDEN_OUTPUTS.has(o.output)) continue;
      ov.push({ id: o.id, color: SERIES[ci++ % SERIES.length]!, points: o.series, dashed: o.kind === "BBANDS" && o.output !== "middle", width: o.kind === "SUPERTREND" ? 2 : 1 });
    }
    const kinds = [...new Set(d.oscillators.map((o) => o.kind))];
    for (const o of d.oscillators) {
      const pane = kinds.indexOf(o.kind) + 1;
      ov.push({ id: o.id, color: o.output === "signal" ? SERIES[2]! : o.output === "hist" ? SERIES[5]! : SERIES[(pane + 1) % SERIES.length]!, points: o.series, pane, width: o.output === "hist" ? 1 : 2 });
    }
    const last = d.candles[d.candles.length - 1]?.ts;
    const first = d.candles[Math.max(0, d.candles.length - 120)]?.ts;
    if (first && last)
      d.levels.forEach((l, i) =>
        ov.push({ id: `lvl${i}`, color: l.type === "support" ? "rgba(35,196,131,0.55)" : "rgba(234,75,139,0.55)", dashed: true, points: [{ ts: first, value: l.price }, { ts: last, value: l.price }] }),
      );
    // one marker per bar (strongest bias wins), labels live in the side list to avoid clutter
    const byTs = new Map<string, Resp["patterns"][number]>();
    for (const p of d.patterns) if (!byTs.has(p.ts) || p.bias !== "neutral") byTs.set(p.ts, p);
    const mk: Marker[] = showPatterns
      ? [...byTs.values()].slice(-30).map((p) => ({ ts: p.ts, position: p.bias === "bearish" ? "aboveBar" : "belowBar", shape: p.bias === "bearish" ? "arrowDown" : p.bias === "bullish" ? "arrowUp" : "circle" }))
      : [];
    return { overlays: ov, markers: mk };
  }, [d, showPatterns]);

  const oscKinds = d ? [...new Set(d.oscillators.map((o) => o.kind))] : [];
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={CandlestickChart}
        title="Technical Analysis"
        description="Multi-indicator chart, candlestick patterns, support/resistance and multi-timeframe trend"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <Field label="Symbol" className="min-w-[220px]">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="h-9 shrink-0 px-2 font-mono text-xs">
                  {symbol}
                </Badge>
                <SymbolSearch onPick={setSymbol} placeholder="Change…" className="w-40" />
              </div>
            </Field>
            <Field label="Interval">
              <Select value={interval} onValueChange={setInterval} options={INTERVALS.map((i) => ({ value: i, label: i }))} />
            </Field>
            <Field label="Indicators" className="min-w-0 flex-1">
              <div className="flex flex-wrap gap-1">
                {INDICATORS.map((i) => {
                  const on = sel.includes(i.id);
                  return (
                    <button
                      key={i.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setSel(on ? sel.filter((x) => x !== i.id) : [...sel, i.id])}
                      className={cn("rounded-full border px-2 py-0.5 text-2xs transition-colors", on ? "border-primary bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent")}
                    >
                      {i.label}
                    </button>
                  );
                })}
                <button
                  type="button"
                  aria-pressed={showPatterns}
                  onClick={() => setShowPatterns(!showPatterns)}
                  className={cn("rounded-full border px-2 py-0.5 text-2xs", showPatterns ? "border-warning bg-warning/15 text-warning" : "text-muted-foreground")}
                >
                  Patterns
                </button>
              </div>
            </Field>
          </>
        }
        csv={d ? { filename: `${symbol.replace(":", "_")}-${interval}`, rows: () => d.candles.map((c, i) => ({ ...c, ...Object.fromEntries([...d.overlays, ...d.oscillators].map((o) => [o.id, o.series[i]?.value ?? null])) })) } : undefined}
        ask={d ? { question: `Give me a technical read on ${symbol} (${interval}): trend, momentum, key levels and recent patterns.`, context: () => ({ symbol, interval, summary: d.summary, mtf: d.mtf, levels: d.levels, patterns: d.patterns.slice(-8), last_close: d.candles.at(-1)?.close }) } : undefined}
      />
      {q.isError ? (
        <EmptyState title="No data" description={(q.error as Error).message} />
      ) : !d ? (
        <Skeleton className="h-[640px]" />
      ) : (
        <div className="grid gap-3 xl:grid-cols-4">
          <Card className="xl:col-span-3">
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                {symbol} · {interval} <TrendBadge t={d.summary} />
              </CardTitle>
              <span className="text-2xs text-muted-foreground">{oscKinds.length ? `panes: price, ${oscKinds.join(", ")}` : ""}</span>
            </CardHeader>
            <CardContent>
              <PriceChart candles={d.candles} overlays={overlays} markers={markers} height={420 + oscKinds.length * 110} live={ticks[symbol]?.ltp ?? null} />
            </CardContent>
          </Card>
          <div className="flex flex-col gap-3">
            <Card>
              <CardHeader>
                <CardTitle>Multi-timeframe</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {Object.entries(d.mtf).map(([tf, t]) => (
                  <div key={tf} className="flex items-center justify-between rounded-md border p-2 text-xs">
                    <span className="w-10 font-semibold">{tf}</span>
                    <TrendBadge t={t} />
                    <span className="num text-muted-foreground">
                      RSI {num(t.rsi, 0)} · ADX {num(t.adx, 0)}
                    </span>
                  </div>
                ))}
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Score" value={d.summary.score ?? "—"} hint="−5 … +5" tone={(d.summary.score ?? 0) > 0 ? "profit" : (d.summary.score ?? 0) < 0 ? "loss" : "default"} />
                  <Stat label="Supertrend" value={d.summary.supertrend ?? "—"} tone={d.summary.supertrend === "up" ? "profit" : "loss"} />
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Support / resistance</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-1">
                {[...d.levels]
                  .sort((a, b) => b.price - a.price)
                  .map((l) => (
                    <div key={l.price} className="flex items-center justify-between text-xs">
                      <Badge variant={l.type === "support" ? "profit" : "loss"}>{l.type}</Badge>
                      <span className="num font-medium">{num(l.price)}</span>
                      <span className="text-2xs text-muted-foreground">
                        {l.touches} touches · {num(((l.price - (d.candles.at(-1)?.close ?? l.price)) / l.price) * 100, 1)}%
                      </span>
                    </div>
                  ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Recent patterns</CardTitle>
              </CardHeader>
              <CardContent className="flex max-h-56 flex-col gap-1 overflow-auto scrollbar-thin">
                {d.patterns.length === 0 && <p className="text-xs text-muted-foreground">None in the last 60 bars.</p>}
                {[...d.patterns]
                  .reverse()
                  .slice(0, 20)
                  .map((p, i) => (
                    <div key={i} className="flex items-center justify-between text-xs">
                      <span className={cn("capitalize", p.bias === "bullish" ? "text-profit" : p.bias === "bearish" ? "text-loss" : "")}>{p.pattern.replace(/_/g, " ")}</span>
                      <span className="text-2xs text-muted-foreground">
                        {shortDate(p.ts)} · {num(p.price)}
                      </span>
                    </div>
                  ))}
              </CardContent>
            </Card>
          </div>
          <Disclaimer className="xl:col-span-4" />
        </div>
      )}
    </div>
  );
}

export default function TechnicalPage() {
  return (
    <React.Suspense>
      <Inner />
    </React.Suspense>
  );
}
