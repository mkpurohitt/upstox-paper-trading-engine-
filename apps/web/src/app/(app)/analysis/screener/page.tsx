"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { BellRing, Filter, Play, Plus, Save, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";
import { Disclaimer, EmptyState } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton, Switch } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { apiJson } from "@/lib/api";
import { num, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

type Op = ">" | "<" | ">=" | "<=" | "==" | "between";
interface Cond { field: string; op: Op; value: number; value2?: number | null }
interface Query { universe: string; logic: "all" | "any"; conditions: Cond[]; sectors: string[]; sort_by: string; descending: boolean; limit: number }
type FieldMeta = Record<string, { label: string; group: string; unit: string }>;
type Row = Record<string, string | number | null> & { symbol: string; name: string; sector: string };
interface RunResp { universe: string; scanned: number; matched: number; rows: Row[]; summary: Record<string, number> }
interface Saved { id: number; name: string; query: Query; alert_enabled: boolean; schedule_minutes: number; last_run_at: string | null; last_results: unknown[] }

const PRESETS: Record<string, { label: string; q: Partial<Query> }> = {
  oversold_quality: { label: "Oversold quality", q: { conditions: [{ field: "rsi14", op: "<", value: 35 }, { field: "roe_pct", op: ">", value: 15 }], sort_by: "rsi14", descending: false } },
  momentum: { label: "Near 52W high + volume", q: { conditions: [{ field: "dist_52w_high_pct", op: "<", value: 3 }, { field: "volume_ratio", op: ">", value: 1.2 }], sort_by: "ret_3m_pct" } },
  value: { label: "Value & yield", q: { conditions: [{ field: "pe", op: "<", value: 18 }, { field: "pb", op: "<", value: 3 }, { field: "dividend_yield_pct", op: ">", value: 1.5 }], sort_by: "dividend_yield_pct" } },
  trend: { label: "Strong uptrend", q: { conditions: [{ field: "dist_sma50_pct", op: ">", value: 0 }, { field: "dist_sma200_pct", op: ">", value: 0 }, { field: "adx14", op: ">", value: 25 }], sort_by: "adx14" } },
  low_debt_growth: { label: "Low debt growth", q: { conditions: [{ field: "debt_to_equity", op: "<", value: 0.5 }, { field: "revenue_growth_3y_pct", op: ">", value: 12 }], sort_by: "revenue_growth_3y_pct" } },
};
const DEFAULT: Query = { universe: "NIFTY100", logic: "all", conditions: PRESETS.oversold_quality!.q.conditions!, sectors: [], sort_by: "rsi14", descending: false, limit: 100 };
const COLUMNS = ["close", "change_pct", "ret_1m_pct", "ret_1y_pct", "rsi14", "dist_sma200_pct", "dist_52w_high_pct", "volume_ratio", "adx14", "pe", "pb", "roe_pct", "debt_to_equity", "dividend_yield_pct", "market_cap_cr"];

function ResultsTable({ rows, fields, extraCols }: { rows: Row[]; fields: FieldMeta; extraCols: string[] }) {
  const parent = React.useRef<HTMLDivElement>(null);
  const cols = [...new Set([...extraCols, ...COLUMNS])].filter((c) => fields[c]);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 34, overscan: 10 });
  const grid = `minmax(180px,1.6fr) repeat(${cols.length}, minmax(78px,1fr))`;
  return (
    <div ref={parent} className="max-h-[560px] overflow-auto scrollbar-thin" role="table" aria-rowcount={rows.length}>
      <div className="min-w-[1400px]">
        <div className="sticky top-0 z-10 grid border-b bg-card text-2xs font-medium uppercase text-muted-foreground" style={{ gridTemplateColumns: grid }} role="row">
          <div className="px-3 py-2">Company</div>
          {cols.map((c) => (
            <div key={c} className={cn("px-2 py-2 text-right", extraCols.includes(c) && "text-primary")} title={fields[c]?.label}>
              {fields[c]?.label.replace(" (₹ Cr)", "").replace("% ", "")}
            </div>
          ))}
        </div>
        <div style={{ height: v.getTotalSize(), position: "relative" }}>
          {v.getVirtualItems().map((it) => {
            const r = rows[it.index]!;
            return (
              <div
                key={r.symbol}
                role="row"
                className="absolute left-0 grid w-full border-b text-xs hover:bg-muted/40"
                style={{ gridTemplateColumns: grid, height: it.size, transform: `translateY(${it.start}px)` }}
              >
                <div className="flex min-w-0 flex-col justify-center px-3">
                  <Link href={`/analysis/technical?symbol=${encodeURIComponent(r.symbol)}`} className="truncate font-medium hover:text-primary">
                    {r.symbol.replace("NSE:", "")}
                  </Link>
                  <span className="truncate text-2xs text-muted-foreground">{r.sector}</span>
                </div>
                {cols.map((c) => {
                  const val = r[c] as number | null;
                  const signed = c.endsWith("_pct") && (c.startsWith("ret") || c.startsWith("change") || c.startsWith("dist_sma"));
                  return (
                    <div key={c} className={cn("num flex items-center justify-end px-2", signed && val !== null && (val >= 0 ? "text-profit" : "text-loss"))}>
                      {c === "market_cap_cr" ? `${num((val ?? 0) / 1000, 0)}K` : num(val, c === "close" ? 2 : 1)}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function ScreenerPage() {
  const qc = useQueryClient();
  const [query, setQuery] = React.useState<Query>(DEFAULT);
  const [submitted, setSubmitted] = React.useState<Query>(DEFAULT);
  const [savedId, setSavedId] = React.useState<number | null>(null);
  const [name, setName] = React.useState("Oversold quality");
  const fieldsQ = useQuery({ queryKey: ["screener-fields"], queryFn: () => apiJson<FieldMeta>("/api/analysis/screener/fields"), staleTime: Infinity });
  const run = useQuery({ queryKey: ["screener", submitted], queryFn: () => apiJson<RunResp>("/api/analysis/screener/run", { method: "POST", body: JSON.stringify(submitted) }) });
  const saved = useQuery({ queryKey: ["screens"], queryFn: () => apiJson<Saved[]>("/api/analysis/screens") });
  const fields = fieldsQ.data ?? {};
  const fieldOpts = Object.entries(fields).map(([k, f]) => ({ value: k, label: `${f.label}${f.group === "fundamental" ? " ·F" : ""}` }));

  const save = useMutation({
    mutationFn: (alert: boolean) => {
      const body = JSON.stringify({ name, query, alert_enabled: alert, schedule_minutes: 60 });
      return savedId ? apiJson<Saved>(`/api/analysis/screens/${savedId}`, { method: "PUT", body }) : apiJson<Saved>("/api/analysis/screens", { method: "POST", body });
    },
    onSuccess: (s) => {
      setSavedId(s.id);
      toast.success(`Saved "${s.name}"`);
      void qc.invalidateQueries({ queryKey: ["screens"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const toggleAlert = useMutation({
    mutationFn: (s: Saved) => apiJson<Saved>(`/api/analysis/screens/${s.id}`, { method: "PUT", body: JSON.stringify({ name: s.name, query: s.query, alert_enabled: !s.alert_enabled, schedule_minutes: s.schedule_minutes }) }),
    onSuccess: (s) => {
      toast.success(s.alert_enabled ? `Alerts on: you'll be notified when new stocks match "${s.name}"` : "Alerts off");
      void qc.invalidateQueries({ queryKey: ["screens"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiJson(`/api/analysis/screens/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      if (id === savedId) setSavedId(null);
      void qc.invalidateQueries({ queryKey: ["screens"] });
    },
  });

  const setCond = (i: number, patch: Partial<Cond>) => setQuery((q) => ({ ...q, conditions: q.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) }));
  const d = run.data;
  const condFields = submitted.conditions.map((c) => c.field);
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Filter}
        title="Stock Screener"
        description="Combine technical and fundamental filters; save screens and get alerted when new stocks qualify"
        onRefresh={() => void run.refetch()}
        refreshing={run.isFetching}
        csv={d ? { filename: `screen-${name.replace(/\s+/g, "-").toLowerCase()}`, rows: () => d.rows } : undefined}
        ask={d ? { question: `Review the results of my "${name}" screen. Which names stand out and what risks should I check?`, context: () => ({ query: submitted, matched: d.matched, top: d.rows.slice(0, 15) }) } : undefined}
      />
      <div className="grid gap-3 xl:grid-cols-4">
        <div className="flex flex-col gap-3 xl:col-span-3">
          <Card>
            <CardContent className="flex flex-col gap-3 pt-4">
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Universe">
                  <Select value={query.universe} onValueChange={(v) => setQuery({ ...query, universe: v })} options={["NIFTY50", "NIFTY100", "BANKNIFTY", "FNO"].map((u) => ({ value: u, label: u }))} />
                </Field>
                <Field label="Match">
                  <Select value={query.logic} onValueChange={(v) => setQuery({ ...query, logic: v as "all" | "any" })} options={[{ value: "all", label: "All conditions" }, { value: "any", label: "Any condition" }]} />
                </Field>
                <Field label="Sort by">
                  <Select value={query.sort_by} onValueChange={(v) => setQuery({ ...query, sort_by: v })} options={fieldOpts} />
                </Field>
                <Field label="Order">
                  <Select value={query.descending ? "desc" : "asc"} onValueChange={(v) => setQuery({ ...query, descending: v === "desc" })} options={[{ value: "desc", label: "High → low" }, { value: "asc", label: "Low → high" }]} />
                </Field>
                <Field label="Preset">
                  <Select
                    value={undefined}
                    placeholder="Load preset…"
                    onValueChange={(k) => {
                      const p = PRESETS[k];
                      if (!p) return;
                      const next = { ...DEFAULT, ...query, descending: true, ...p.q };
                      setQuery(next);
                      setSubmitted(next);
                      setName(p.label);
                      setSavedId(null);
                    }}
                    options={Object.entries(PRESETS).map(([k, p]) => ({ value: k, label: p.label }))}
                  />
                </Field>
              </div>
              <div className="flex flex-col gap-1.5">
                {query.conditions.map((c, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-1.5">
                    <span className="w-10 text-right text-2xs uppercase text-muted-foreground">{i === 0 ? "where" : query.logic === "all" ? "and" : "or"}</span>
                    <Select value={c.field} onValueChange={(v) => setCond(i, { field: v })} options={fieldOpts} className="w-56" ariaLabel="Field" />
                    <Select value={c.op} onValueChange={(v) => setCond(i, { op: v as Op })} options={[">", "<", ">=", "<=", "==", "between"].map((o) => ({ value: o, label: o }))} className="w-28" ariaLabel="Operator" />
                    <Input type="number" value={c.value} onChange={(e) => setCond(i, { value: Number(e.target.value) })} className="w-28" aria-label="Value" />
                    {c.op === "between" && <Input type="number" value={c.value2 ?? 0} onChange={(e) => setCond(i, { value2: Number(e.target.value) })} className="w-28" aria-label="Upper value" />}
                    <span className="text-2xs text-muted-foreground">{fields[c.field]?.unit}</span>
                    <Button size="icon-sm" variant="ghost" aria-label="Remove condition" onClick={() => setQuery({ ...query, conditions: query.conditions.filter((_, j) => j !== i) })}>
                      <Trash2 />
                    </Button>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-2 pl-11">
                  <Button size="sm" variant="outline" disabled={query.conditions.length >= 20} onClick={() => setQuery({ ...query, conditions: [...query.conditions, { field: "rsi14", op: ">", value: 50 }] })}>
                    <Plus /> Condition
                  </Button>
                  <Button size="sm" onClick={() => setSubmitted(query)} loading={run.isFetching}>
                    <Play /> Run screen
                  </Button>
                  <div className="ml-auto flex items-center gap-2">
                    <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 w-48" aria-label="Screen name" />
                    <Button size="sm" variant="outline" onClick={() => save.mutate(false)} loading={save.isPending} disabled={!name.trim()}>
                      <Save /> {savedId ? "Update" : "Save"}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => save.mutate(true)} disabled={!name.trim()}>
                      <BellRing /> Save + alert
                    </Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>
                Results {d ? <span className="font-normal text-muted-foreground">· {d.matched} of {d.scanned} matched in {d.universe}</span> : null}
              </CardTitle>
              {d?.summary?.median_rsi !== undefined && <Badge variant="secondary">median RSI {num(d.summary.median_rsi, 1)}</Badge>}
            </CardHeader>
            <CardContent className="p-0">
              {run.isLoading || !fieldsQ.data ? (
                <Skeleton className="m-4 h-80" />
              ) : run.isError ? (
                <EmptyState className="m-4" title="Screen failed" description={(run.error as Error).message} />
              ) : !d || d.rows.length === 0 ? (
                <EmptyState className="m-4" icon={Filter} title="No matches" description="Loosen a condition or switch to 'Any condition'." />
              ) : (
                <ResultsTable rows={d.rows} fields={fields} extraCols={condFields} />
              )}
            </CardContent>
          </Card>
        </div>
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Saved screens</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {saved.isLoading && <Skeleton className="h-24" />}
            {saved.data?.length === 0 && <p className="text-xs text-muted-foreground">Save a screen to re-run it later or get alerts (checked every 5 minutes during market hours).</p>}
            {saved.data?.map((s) => (
              <div key={s.id} className={cn("flex flex-col gap-1 rounded-md border p-2", s.id === savedId && "border-primary")}>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="min-w-0 flex-1 truncate text-left text-sm font-medium hover:text-primary"
                    onClick={() => {
                      const q = { ...DEFAULT, ...s.query };
                      setQuery(q);
                      setSubmitted(q);
                      setName(s.name);
                      setSavedId(s.id);
                    }}
                  >
                    {s.name}
                  </button>
                  <Button size="icon-sm" variant="ghost" aria-label={`Delete ${s.name}`} onClick={() => confirm(`Delete "${s.name}"?`) && remove.mutate(s.id)}>
                    <Trash2 />
                  </Button>
                </div>
                <div className="flex items-center justify-between text-2xs text-muted-foreground">
                  <span>
                    {s.query.universe} · {s.query.conditions.length} cond. {s.last_run_at ? `· ran ${timeAgo(s.last_run_at)} (${s.last_results.length})` : ""}
                  </span>
                  <label className="flex items-center gap-1">
                    <BellRing className={cn("h-3 w-3", s.alert_enabled && "text-warning")} />
                    <Switch checked={s.alert_enabled} onCheckedChange={() => toggleAlert.mutate(s)} aria-label={`Alerts for ${s.name}`} />
                  </label>
                </div>
              </div>
            ))}
            <Disclaimer className="mt-2" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
