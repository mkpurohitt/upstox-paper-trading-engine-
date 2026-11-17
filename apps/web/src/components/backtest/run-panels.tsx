"use client";
import type { Schemas } from "@algo/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical, Play, Sparkles, Wand2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { axisProps, tooltipStyle } from "@/components/charts/theme";
import { EmptyState, Stat } from "@/components/common";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Checkbox, Progress, Skeleton, Switch } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useBacktest } from "@/hooks/use-backtest";
import { useIndicatorCatalog } from "@/hooks/use-catalog";
import { api, unwrap } from "@/lib/api";
import { useBuilder } from "@/lib/builder-store";
import { BROKERS, setPath, tunableParams, type DSL } from "@/lib/dsl";
import { compactNum, inr, num, pct, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BacktestResults } from "./results";

type Kind = "backtest" | "optimise" | "walk_forward";

function defaultRange(tf: string): { start: string; end: string } {
  const days = { "1m": 30, "3m": 45, "5m": 60, "15m": 120, "30m": 200, "1h": 365, "1d": 1460 }[tf] ?? 120;
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400_000);
  const f = (d: Date) => d.toISOString().slice(0, 10);
  return { start: f(start), end: f(end) };
}

interface CommonParams {
  start: string;
  end: string;
  capital: number;
  broker: string;
  slippage: number;
  fill: "next_open" | "close";
}

function ParamsForm({ p, set, extra }: { p: CommonParams; set: (p: CommonParams) => void; extra?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="From">
        <Input type="date" value={p.start} onChange={(e) => set({ ...p, start: e.target.value })} />
      </Field>
      <Field label="To">
        <Input type="date" value={p.end} onChange={(e) => set({ ...p, end: e.target.value })} />
      </Field>
      <Field label="Capital (₹)">
        <Input type="number" value={p.capital} onChange={(e) => set({ ...p, capital: Number(e.target.value) })} />
      </Field>
      <Field label="Broker cost model">
        <Select value={p.broker} onValueChange={(b) => set({ ...p, broker: b })} options={BROKERS.map((b) => ({ value: b, label: b }))} />
      </Field>
      <Field label="Slippage (bps)" className="min-w-[90px]">
        <Input type="number" value={p.slippage} onChange={(e) => set({ ...p, slippage: Number(e.target.value) })} />
      </Field>
      <Field label="Fill">
        <Select value={p.fill} onValueChange={(f) => set({ ...p, fill: f as CommonParams["fill"] })} options={[{ value: "next_open", label: "Next bar open" }, { value: "close", label: "Signal bar close" }]} />
      </Field>
      {extra}
    </div>
  );
}

function useCommonParams(): [CommonParams, (p: CommonParams) => void] {
  const tf = useBuilder((s) => s.dsl.timeframe ?? "15m");
  const [p, set] = React.useState<CommonParams>(() => ({ ...defaultRange(tf), capital: 1_000_000, broker: "zerodha", slippage: 5, fill: "next_open" }));
  React.useEffect(() => set((x) => ({ ...x, ...defaultRange(tf) })), [tf]);
  return [p, set];
}

function useLaunch(kind: Kind, ensureSaved: () => Promise<number | null>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { p: CommonParams; mode?: "event" | "vectorised"; options?: Record<string, unknown> }) => {
      const sid = await ensureSaved();
      const dsl = useBuilder.getState().dsl;
      return unwrap(
        api.POST("/api/backtests", {
          body: {
            ...(sid ? { strategy_id: sid } : { dsl }),
            kind,
            params: {
              start: `${args.p.start}T00:00:00+05:30`,
              end: `${args.p.end}T23:59:00+05:30`,
              initial_capital: args.p.capital,
              broker: args.p.broker,
              slippage_bps: args.p.slippage,
              fill: args.p.fill,
              mode: args.mode ?? "event",
              options: args.options ?? {},
            },
          },
        }),
      );
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["backtests"] }),
    onError: (e: Error) => toast.error(e.message),
  });
}

function JobProgress({ id, children }: { id: number; children: (bt: Schemas["BacktestOut"]) => React.ReactNode }) {
  const { data, progress } = useBacktest(id);
  if (!data) return <Skeleton className="h-40" />;
  if (data.status === "failed") return <EmptyState icon={AlertTriangle} title="Backtest failed" description={data.error ?? "Unknown error"} />;
  if (data.status !== "completed") {
    return (
      <Card>
        <CardContent className="flex flex-col gap-2 pt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-primary" /> {progress?.status === "queued" ? "Queued…" : progress?.message ?? "Running…"}
            </span>
            <span className="num">{Math.round((progress?.progress ?? 0) * 100)}%</span>
          </div>
          <Progress value={(progress?.progress ?? 0) * 100} />
        </CardContent>
      </Card>
    );
  }
  return <>{children(data)}</>;
}

function History({ kind, strategyId, onPick, current }: { kind: Kind; strategyId: number | null; onPick: (id: number) => void; current: number | null }) {
  const q = useQuery({
    queryKey: ["backtests", strategyId],
    queryFn: () => unwrap(api.GET("/api/backtests", { params: { query: { strategy_id: strategyId ?? undefined, limit: 30 } } })),
    enabled: strategyId !== null,
  });
  const rows = (q.data ?? []).filter((b) => b.kind === kind);
  if (!rows.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">History:</span>
      {rows.slice(0, 8).map((b) => (
        <button key={b.id} type="button" onClick={() => onPick(b.id)} className={cn("rounded-md border px-2 py-0.5", current === b.id ? "border-primary bg-primary/10 text-primary" : "hover:bg-accent")}>
          #{b.id} · {b.status === "completed" ? inr((b.metrics as { net_pnl?: number }).net_pnl, { compact: true, signed: true }) : b.status}
        </button>
      ))}
    </div>
  );
}

export function BacktestPanel({ ensureSaved }: { ensureSaved: () => Promise<number | null> }) {
  const strategyId = useBuilder((s) => s.strategyId);
  const [p, setP] = useCommonParams();
  const [mode, setMode] = React.useState<"event" | "vectorised">("event");
  const [mc, setMc] = React.useState(true);
  const [current, setCurrent] = React.useState<number | null>(null);
  const launch = useLaunch("backtest", ensureSaved);
  const last = useQuery({
    queryKey: ["backtests", strategyId],
    queryFn: () => unwrap(api.GET("/api/backtests", { params: { query: { strategy_id: strategyId ?? undefined, limit: 30 } } })),
    enabled: strategyId !== null && current === null,
  });
  React.useEffect(() => {
    if (current === null) {
      const b = last.data?.find((x) => x.kind === "backtest");
      if (b) setCurrent(b.id);
    }
  }, [last.data, current]);
  const run = async () => {
    const bt = await launch.mutateAsync({ p, mode, options: { monte_carlo: mc } });
    setCurrent(bt.id);
  };
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <ParamsForm
            p={p}
            set={setP}
            extra={
              <>
                <Field label="Engine">
                  <Select value={mode} onValueChange={(m) => setMode(m as "event")} options={[{ value: "event", label: "Event-driven (exact)" }, { value: "vectorised", label: "Vectorised (fast)" }]} />
                </Field>
                <label className="flex h-9 items-center gap-2 text-xs">
                  <Switch checked={mc} onCheckedChange={setMc} /> Monte Carlo
                </label>
                <Button onClick={run} loading={launch.isPending} className="ml-auto">
                  <Play /> Run backtest
                </Button>
              </>
            }
          />
          <History kind="backtest" strategyId={strategyId} onPick={setCurrent} current={current} />
        </CardContent>
      </Card>
      {current ? <JobProgress id={current}>{(bt) => <BacktestResults bt={bt} />}</JobProgress> : <EmptyState icon={FlaskConical} title="No backtest yet" description="Pick a date range and run. Costs include brokerage, STT, exchange charges, SEBI fees, stamp duty, GST and slippage." />}
    </div>
  );
}

interface SpaceRow {
  path: string;
  label: string;
  on: boolean;
  min: number;
  max: number;
  step: number;
}

function SpaceEditor({ rows, setRows }: { rows: SpaceRow[]; setRows: (r: SpaceRow[]) => void }) {
  if (!rows.length) return <p className="text-xs text-muted-foreground">No numeric parameters to tune — add indicators or stops first.</p>;
  return (
    <Table>
      <THead>
        <TR>
          <TH />
          <TH>Parameter</TH>
          <TH>Min</TH>
          <TH>Max</TH>
          <TH>Step</TH>
          <TH className="text-right">Values</TH>
        </TR>
      </THead>
      <TBody>
        {rows.map((r, i) => (
          <TR key={r.path}>
            <TD>
              <Checkbox checked={r.on} onCheckedChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, on: v === true } : x)))} aria-label={`Tune ${r.label}`} />
            </TD>
            <TD className="font-mono text-xs">{r.label}</TD>
            {(["min", "max", "step"] as const).map((k) => (
              <TD key={k}>
                <Input className="h-7 w-20 text-xs" type="number" step="any" value={r[k]} disabled={!r.on} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, [k]: Number(e.target.value) } : x)))} />
              </TD>
            ))}
            <TD className="text-right text-xs text-muted-foreground">{r.on ? Math.max(1, Math.floor((r.max - r.min) / (r.step || 1)) + 1) : "—"}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function useSpace(): [SpaceRow[], (r: SpaceRow[]) => void] {
  const dsl = useBuilder((s) => s.dsl);
  const { data: catalog } = useIndicatorCatalog();
  const [rows, setRows] = React.useState<SpaceRow[]>([]);
  React.useEffect(() => {
    const t = tunableParams(dsl, catalog);
    setRows(
      t.map((x, i) => {
        const isInt = Number.isInteger(x.value) && x.value >= 2;
        const lo = isInt ? Math.max(x.min, Math.round(x.value * 0.5)) : Math.max(x.min, +(x.value * 0.5).toFixed(2));
        const hi = isInt ? Math.min(x.max, Math.round(x.value * 1.5)) : Math.min(x.max, +(x.value * 1.5).toFixed(2));
        const step = isInt ? Math.max(1, Math.round((hi - lo) / 4)) : +((hi - lo) / 4).toFixed(2) || 0.1;
        return { path: x.path, label: x.label, on: i < 2, min: lo, max: hi, step };
      }),
    );
  }, [dsl.indicators, dsl.exit?.stop_loss, dsl.exit?.target, dsl.pair, catalog]); // eslint-disable-line react-hooks/exhaustive-deps
  return [rows, setRows];
}

export function OptimisePanel({ ensureSaved }: { ensureSaved: () => Promise<number | null> }) {
  const [p, setP] = useCommonParams();
  const [rows, setRows] = useSpace();
  const [method, setMethod] = React.useState("grid");
  const [objective, setObjective] = React.useState("sharpe");
  const [oos, setOos] = React.useState(30);
  const [current, setCurrent] = React.useState<number | null>(null);
  const strategyId = useBuilder((s) => s.strategyId);
  const launch = useLaunch("optimise", ensureSaved);
  const update = useBuilder((s) => s.update);
  const space = rows.filter((r) => r.on).map((r) => ({ path: r.path, min: r.min, max: r.max, step: r.step }));
  const run = async () => {
    if (!space.length) return toast.error("Select at least one parameter");
    const bt = await launch.mutateAsync({ p, mode: "vectorised", options: { space, method, objective, oos_fraction: oos / 100 } });
    setCurrent(bt.id);
  };
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <ParamsForm p={p} set={setP} />
          <SpaceEditor rows={rows} setRows={setRows} />
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Search">
              <Select value={method} onValueChange={setMethod} options={[{ value: "grid", label: "Grid (≤400)" }, { value: "random", label: "Random (60)" }]} />
            </Field>
            <Field label="Objective">
              <Select value={objective} onValueChange={setObjective} options={["sharpe", "sortino", "calmar", "cagr_pct", "profit_factor", "net_pnl"].map((o) => ({ value: o, label: o }))} />
            </Field>
            <Field label="Out-of-sample %">
              <Input type="number" value={oos} min={0} max={50} onChange={(e) => setOos(Number(e.target.value))} />
            </Field>
            <Button onClick={run} loading={launch.isPending} className="ml-auto">
              <Wand2 /> Optimise
            </Button>
          </div>
          <History kind="optimise" strategyId={strategyId} onPick={setCurrent} current={current} />
        </CardContent>
      </Card>
      {current && (
        <JobProgress id={current}>
          {(bt) => {
            const o = (bt.extra as { optimisation: Record<string, unknown> }).optimisation;
            const results = o.results as { params: Record<string, number>; metrics: Record<string, number>; score: number }[];
            const best = o.best as { params: Record<string, number>; metrics: Record<string, number> };
            const warnings = (o.warnings as string[]) ?? [];
            const heat = o.heatmap as { x: string; y: string; cells: { x: number; y: number; value: number | null }[] } | null;
            return (
              <div className="flex flex-col gap-3">
                {warnings.map((w, i) => (
                  <p key={i} className="flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning/5 p-2 text-xs text-warning">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w}
                  </p>
                ))}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label={`Best ${String(o.objective)}`} value={num(best.metrics[String(o.objective)])} tone="profit" />
                  <Stat label="Combinations" value={String(o.combinations)} />
                  <Stat label="OOS Sharpe" value={num((o.oos_metrics as Record<string, number> | null)?.sharpe)} hint={`in-sample ${num(best.metrics.sharpe)}`} />
                  <Stat label="Deflated Sharpe P" value={o.deflated_sharpe_prob === null ? "—" : num(o.deflated_sharpe_prob as number, 2)} tone={(o.deflated_sharpe_prob as number) >= 0.95 ? "profit" : "warning"} />
                </div>
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0">
                    <CardTitle>Best parameters</CardTitle>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        update((d) => {
                          let next: DSL = d;
                          for (const [k, v] of Object.entries(best.params)) next = setPath(next, k, v);
                          return next;
                        });
                        toast.success("Best parameters applied to the strategy — save to create a new version");
                      }}
                    >
                      <Sparkles /> Apply to strategy
                    </Button>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    {Object.entries(best.params).map(([k, v]) => (
                      <Badge key={k} variant="default" className="text-xs">
                        {k.split(".").slice(-3).join(".")} = {String(v)}
                      </Badge>
                    ))}
                  </CardContent>
                </Card>
                {heat && <Heatmap heat={heat} />}
                <Card>
                  <CardHeader>
                    <CardTitle>Top results (in-sample)</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <THead>
                        <TR>
                          {Object.keys(best.params).map((k) => (
                            <TH key={k}>{k.split(".").slice(-2).join(".")}</TH>
                          ))}
                          <TH className="text-right">Sharpe</TH>
                          <TH className="text-right">CAGR</TH>
                          <TH className="text-right">Max DD</TH>
                          <TH className="text-right">Trades</TH>
                          <TH className="text-right">Net P&L</TH>
                        </TR>
                      </THead>
                      <TBody>
                        {results.slice(0, 15).map((r, i) => (
                          <TR key={i} className={i === 0 ? "bg-primary/5" : ""}>
                            {Object.values(r.params).map((v, j) => (
                              <TD key={j} className="font-mono">
                                {String(v)}
                              </TD>
                            ))}
                            <TD className="text-right">{num(r.metrics.sharpe)}</TD>
                            <TD className="text-right">{pct(r.metrics.cagr_pct)}</TD>
                            <TD className="text-right text-loss">{pct(r.metrics.max_drawdown_pct)}</TD>
                            <TD className="text-right">{r.metrics.trades}</TD>
                            <TD className="text-right">{inr(r.metrics.net_pnl, { compact: true, signed: true })}</TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  </CardContent>
                </Card>
              </div>
            );
          }}
        </JobProgress>
      )}
    </div>
  );
}

function Heatmap({ heat }: { heat: { x: string; y: string; cells: { x: number; y: number; value: number | null }[] } }) {
  const xs = [...new Set(heat.cells.map((c) => c.x))].sort((a, b) => a - b);
  const ys = [...new Set(heat.cells.map((c) => c.y))].sort((a, b) => b - a);
  const vals = heat.cells.map((c) => c.value).filter((v): v is number => v !== null);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Parameter heatmap — look for broad plateaus, not isolated peaks</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="border-separate border-spacing-0.5 text-2xs num">
          <tbody>
            {ys.map((y) => (
              <tr key={y}>
                <td className="pr-2 text-right text-muted-foreground">{y}</td>
                {xs.map((x) => {
                  const v = heat.cells.find((c) => c.x === x && c.y === y)?.value ?? null;
                  const t = v === null || hi === lo ? 0 : (v - lo) / (hi - lo);
                  return (
                    <td key={x} className="h-8 w-14 rounded text-center" style={{ background: v === null ? "hsl(var(--muted))" : `hsl(var(--primary) / ${0.1 + t * 0.8})` }} title={`${heat.x.split(".").slice(-2).join(".")}=${x}, ${heat.y.split(".").slice(-2).join(".")}=${y}: ${v?.toFixed(2)}`}>
                      {v?.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <td />
              {xs.map((x) => (
                <td key={x} className="text-center text-muted-foreground">
                  {x}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        <p className="mt-1 text-2xs text-muted-foreground">
          x: {heat.x} · y: {heat.y}
        </p>
      </CardContent>
    </Card>
  );
}

export function WalkForwardPanel({ ensureSaved }: { ensureSaved: () => Promise<number | null> }) {
  const tf = useBuilder((s) => s.dsl.timeframe ?? "15m");
  const [p, setP] = useCommonParams();
  const [rows, setRows] = useSpace();
  const [windows, setWindows] = React.useState(5);
  const [train, setTrain] = React.useState(70);
  const [current, setCurrent] = React.useState<number | null>(null);
  const strategyId = useBuilder((s) => s.strategyId);
  const launch = useLaunch("walk_forward", ensureSaved);
  React.useEffect(() => {
    if (tf === "1d") setP({ ...p, start: new Date(Date.now() - 5 * 365 * 86400_000).toISOString().slice(0, 10) });
  }, [tf]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    const space = rows.filter((r) => r.on).map((r) => ({ path: r.path, min: r.min, max: r.max, step: r.step }));
    if (!space.length) return toast.error("Select at least one parameter");
    const bt = await launch.mutateAsync({ p, mode: "vectorised", options: { space, windows, train_ratio: train / 100 } });
    setCurrent(bt.id);
  };
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <ParamsForm p={p} set={setP} />
          <SpaceEditor rows={rows} setRows={setRows} />
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Windows">
              <Input type="number" min={2} max={12} value={windows} onChange={(e) => setWindows(Number(e.target.value))} />
            </Field>
            <Field label="Train %">
              <Input type="number" min={50} max={90} value={train} onChange={(e) => setTrain(Number(e.target.value))} />
            </Field>
            <Button onClick={run} loading={launch.isPending} className="ml-auto">
              <Play /> Run walk-forward
            </Button>
          </div>
          <History kind="walk_forward" strategyId={strategyId} onPick={setCurrent} current={current} />
        </CardContent>
      </Card>
      {current && (
        <JobProgress id={current}>
          {(bt) => {
            const wf = (bt.extra as { walk_forward: Record<string, unknown> }).walk_forward;
            const wins = wf.windows as { window: number; test: string[]; best_params: Record<string, number>; is_metrics: Record<string, number>; oos_metrics: Record<string, number> }[];
            const oos = wf.oos_metrics as Record<string, number>;
            return (
              <div className="flex flex-col gap-3">
                {((wf.warnings as string[]) ?? []).map((w, i) => (
                  <p key={i} className="flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning/5 p-2 text-xs text-warning">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5" /> {w}
                  </p>
                ))}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="WF efficiency" value={num(wf.walk_forward_efficiency as number)} tone={(wf.walk_forward_efficiency as number) >= 0.5 ? "profit" : "warning"} hint="OOS / IS CAGR" />
                  <Stat label="OOS return" value={pct(oos.total_return_pct)} tone={(oos.total_return_pct ?? 0) >= 0 ? "profit" : "loss"} />
                  <Stat label="OOS Sharpe" value={num(oos.sharpe)} />
                  <Stat label="OOS max DD" value={pct(oos.max_drawdown_pct)} tone="loss" />
                </div>
                <Card>
                  <CardHeader>
                    <CardTitle>Stitched out-of-sample equity</CardTitle>
                  </CardHeader>
                  <CardContent className="h-56">
                    <ResponsiveContainer>
                      <LineChart data={bt.equity_curve} margin={{ left: 0, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                        <XAxis dataKey="ts" {...axisProps} tickFormatter={(t: string) => shortDate(t)} minTickGap={40} />
                        <YAxis {...axisProps} width={60} tickFormatter={(v: number) => compactNum(v)} domain={["auto", "auto"]} />
                        <RTooltip {...tooltipStyle} formatter={(v: number) => inr(v, { decimals: 0 })} />
                        <Line type="monotone" dataKey="value" stroke="hsl(var(--primary))" dot={false} strokeWidth={2} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
                <Table>
                  <THead>
                    <TR>
                      <TH>#</TH>
                      <TH>Test window</TH>
                      <TH>Chosen params</TH>
                      <TH className="text-right">IS Sharpe</TH>
                      <TH className="text-right">OOS Sharpe</TH>
                      <TH className="text-right">OOS return</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {wins.map((w) => (
                      <TR key={w.window}>
                        <TD>{w.window}</TD>
                        <TD className="text-xs text-muted-foreground">
                          {shortDate(w.test[0]!)} → {shortDate(w.test[1]!)}
                        </TD>
                        <TD className="font-mono text-2xs">
                          {Object.entries(w.best_params)
                            .map(([k, v]) => `${k.split(".").slice(-2, -1)}=${v}`)
                            .join(" ")}
                        </TD>
                        <TD className="text-right">{num(w.is_metrics.sharpe)}</TD>
                        <TD className="text-right">{num(w.oos_metrics.sharpe)}</TD>
                        <TD className={cn("text-right", (w.oos_metrics.total_return_pct ?? 0) >= 0 ? "text-profit" : "text-loss")}>{pct(w.oos_metrics.total_return_pct)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            );
          }}
        </JobProgress>
      )}
    </div>
  );
}
