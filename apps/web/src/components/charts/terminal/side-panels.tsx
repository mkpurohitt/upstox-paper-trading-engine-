"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Eye, EyeOff, Lock, Plus, RotateCcw, Trash2, Unlock, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { SymbolSearch } from "@/components/symbol-picker";
import { Button } from "@/components/ui/button";
import { useTicks } from "@/hooks/use-realtime";
import { apiJson } from "@/lib/api";
import { TOOL_LABEL } from "@/lib/chart/drawings";
import { INDICATOR_BY_ID, indicatorLabel } from "@/lib/chart/indicators";
import { fmtPrice, fmtVolume } from "@/lib/chart/series";
import { cn } from "@/lib/utils";
import { shortSymbol } from "./chart-cell";
import { NO_DRAWINGS, useTerminal } from "./store";

const DEFAULT_WATCH = ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "BSE_INDEX:SENSEX", "NSE:RELIANCE", "NSE:HDFCBANK", "NSE:ICICIBANK", "NSE:INFY", "NSE:TCS", "NSE:SBIN", "NSE:BHARTIARTL", "MCX:CRUDEOIL", "MCX:GOLD"];

interface WL {
  id: number;
  name: string;
  symbols: string[];
}

function useActiveSymbol() {
  const active = useTerminal((s) => s.layout.active);
  const symbol = useTerminal((s) => s.layout.cells[s.layout.active]!.symbol);
  return { active, symbol };
}

export function WatchlistPanel() {
  const qc = useQueryClient();
  const { active, symbol } = useActiveSymbol();
  const setCell = useTerminal((s) => s.setCell);
  const wlId = useTerminal((s) => s.layout.watchlistId);
  const setLayout = useTerminal((s) => s.setLayout);
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: () => apiJson<WL[]>("/api/watchlists") });
  const creating = React.useRef(false);
  React.useEffect(() => {
    if (lists.data && lists.data.length === 0 && !creating.current) {
      creating.current = true;
      void apiJson<WL>("/api/watchlists", { method: "POST", body: JSON.stringify({ name: "Watchlist", symbols: DEFAULT_WATCH }) }).then(() => qc.invalidateQueries({ queryKey: ["watchlists"] }));
    }
  }, [lists.data, qc]);
  const current = lists.data?.find((w) => w.id === wlId) ?? lists.data?.[0];
  const save = useMutation({
    mutationFn: (symbols: string[]) => apiJson<WL>(`/api/watchlists/${current!.id}`, { method: "PUT", body: JSON.stringify({ name: current!.name, symbols }) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["watchlists"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  const symbols = current?.symbols ?? [];
  const ticks = useTicks(symbols);
  const quotes = useQuery({
    queryKey: ["wl-quotes", symbols.join(",")],
    queryFn: () => apiJson<{ symbol: string; ltp: number; change_pct: number | null }[]>(`/api/market/quotes?symbols=${encodeURIComponent(symbols.join(","))}`),
    enabled: symbols.length > 0,
    staleTime: 15_000,
  });
  const qmap = Object.fromEntries((quotes.data ?? []).map((q) => [q.symbol, q]));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b p-2">
        <select
          className="h-7 min-w-0 flex-1 rounded border bg-background px-1 text-xs"
          aria-label="Watchlist"
          value={current?.id ?? ""}
          onChange={(e) => setLayout((l) => ({ ...l, watchlistId: Number(e.target.value) }))}
        >
          {(lists.data ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.name} ({w.symbols.length})
            </option>
          ))}
        </select>
        <Button
          size="xs"
          variant="outline"
          disabled={!current || symbols.includes(symbol)}
          onClick={() => save.mutate([...symbols, symbol])}
          title={`Add ${shortSymbol(symbol)}`}
        >
          <Plus className="h-3 w-3" /> {shortSymbol(symbol).slice(0, 10)}
        </Button>
      </div>
      <div className="border-b p-2">
        <SymbolSearch placeholder="Add symbol…" onPick={(s) => current && !symbols.includes(s) && save.mutate([...symbols, s])} />
      </div>
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 border-b px-3 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>Symbol</span>
        <span className="text-right">Last</span>
        <span className="w-14 text-right">Chg%</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {symbols.map((s) => {
          const t = ticks[s];
          const ltp = t?.ltp ?? qmap[s]?.ltp;
          const pct = t?.change_pct ?? qmap[s]?.change_pct;
          return (
            <div
              key={s}
              role="button"
              tabIndex={0}
              onClick={() => setCell(active, { symbol: s })}
              onKeyDown={(e) => e.key === "Enter" && setCell(active, { symbol: s })}
              className={cn("group grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-x-2 px-3 py-1.5 text-xs hover:bg-muted/60", s === symbol && "bg-primary/10")}
            >
              <span className="min-w-0 truncate font-medium">{shortSymbol(s)}</span>
              <span className="num text-right">{fmtPrice(ltp)}</span>
              <span className={cn("num relative w-14 text-right", (pct ?? 0) >= 0 ? "text-profit" : "text-loss")}>
                <span className="group-hover:invisible">{pct != null ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "—"}</span>
                <button
                  aria-label={`Remove ${s}`}
                  className="invisible absolute right-0 top-0 rounded p-0.5 text-muted-foreground hover:text-loss group-hover:visible"
                  onClick={(e) => {
                    e.stopPropagation();
                    save.mutate(symbols.filter((x) => x !== s));
                  }}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            </div>
          );
        })}
        {lists.isLoading && <p className="p-3 text-xs text-muted-foreground">Loading…</p>}
      </div>
    </div>
  );
}

interface Quote {
  symbol: string;
  name?: string | null;
  ltp: number;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  oi?: number | null;
  avg_price?: number | null;
  upper_circuit?: number | null;
  lower_circuit?: number | null;
  week52_high?: number | null;
  week52_low?: number | null;
  total_buy_qty?: number | null;
  total_sell_qty?: number | null;
  bids: { price: number; quantity: number; orders: number }[];
  asks: { price: number; quantity: number; orders: number }[];
}

function RangeBar({ low, high, value, label }: { low?: number | null; high?: number | null; value: number; label: string }) {
  if (low == null || high == null || high <= low) return null;
  const pct = Math.max(0, Math.min(100, ((value - low) / (high - low)) * 100));
  return (
    <div className="text-[11px]">
      <div className="mb-1 flex justify-between text-muted-foreground">
        <span>{fmtPrice(low)}</span>
        <span>{label}</span>
        <span>{fmtPrice(high)}</span>
      </div>
      <div className="relative h-1 rounded bg-muted">
        <span className="absolute -top-1 h-3 w-0.5 rounded bg-foreground" style={{ left: `${pct}%` }} />
      </div>
    </div>
  );
}

export function DetailsPanel() {
  const { symbol } = useActiveSymbol();
  const q = useQuery({ queryKey: ["quote", symbol], queryFn: () => apiJson<Quote>(`/api/market/quote/${encodeURIComponent(symbol)}`), refetchInterval: 3000 });
  const tick = useTicks([symbol])[symbol];
  const d = q.data;
  if (!d) return <p className="p-3 text-xs text-muted-foreground">{q.error ? (q.error as Error).message : "Loading…"}</p>;
  const ltp = tick?.ltp ?? d.ltp;
  const chg = tick?.change ?? d.change;
  const pct = tick?.change_pct ?? d.change_pct;
  const maxQty = Math.max(1, ...d.bids.map((b) => b.quantity), ...d.asks.map((a) => a.quantity));
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 text-xs">
      <div>
        <p className="font-semibold">{shortSymbol(symbol)}</p>
        <p className="truncate text-muted-foreground">{d.name ?? symbol}</p>
        <p className="num mt-1 text-xl font-semibold">{fmtPrice(ltp)}</p>
        <p className={cn("num", (chg ?? 0) >= 0 ? "text-profit" : "text-loss")}>
          {chg != null ? `${chg >= 0 ? "+" : ""}${fmtPrice(chg)}` : "—"} {pct != null ? `(${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)` : ""}
        </p>
      </div>
      <RangeBar low={d.low} high={d.high} value={ltp} label="Day range" />
      <RangeBar low={d.week52_low} high={d.week52_high} value={ltp} label="52-week range" />
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
        {(
          [
            ["Open", fmtPrice(d.open)],
            ["Prev close", fmtPrice(d.close)],
            ["Volume", fmtVolume(d.volume)],
            ["Avg price", fmtPrice(d.avg_price)],
            ["Upper circuit", fmtPrice(d.upper_circuit)],
            ["Lower circuit", fmtPrice(d.lower_circuit)],
            ...(d.oi ? [["Open interest", fmtVolume(d.oi)]] : []),
          ] as [string, string][]
        ).map(([k, v]) => (
          <React.Fragment key={k}>
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="num text-right">{v}</dd>
          </React.Fragment>
        ))}
      </dl>
      {(d.bids.length > 0 || d.asks.length > 0) && (
        <div>
          <p className="mb-1 font-medium">Market depth</p>
          <div className="grid grid-cols-2 gap-2">
            {(["bids", "asks"] as const).map((side) => (
              <table key={side} className="w-full text-[11px]">
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="text-left font-normal">{side === "bids" ? "Bid" : "Ask"}</th>
                    <th className="text-right font-normal">Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {d[side].slice(0, 5).map((l, i) => (
                    <tr key={i} className="relative">
                      <td className={cn("num relative z-10", side === "bids" ? "text-profit" : "text-loss")}>{fmtPrice(l.price)}</td>
                      <td className="num relative z-10 text-right">
                        <span className={cn("absolute inset-y-0 right-0 -z-10 rounded-sm", side === "bids" ? "bg-profit/15" : "bg-loss/15")} style={{ width: `${(l.quantity / maxQty) * 100}%` }} />
                        {fmtVolume(l.quantity)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
          </div>
          {d.total_buy_qty != null && d.total_sell_qty != null && d.total_buy_qty + d.total_sell_qty > 0 && (
            <div className="mt-2">
              <div className="flex h-1.5 overflow-hidden rounded">
                <span className="bg-profit" style={{ width: `${(d.total_buy_qty / (d.total_buy_qty + d.total_sell_qty)) * 100}%` }} />
                <span className="flex-1 bg-loss" />
              </div>
              <p className="mt-1 flex justify-between text-[10px] text-muted-foreground">
                <span>Buy {fmtVolume(d.total_buy_qty)}</span>
                <span>Sell {fmtVolume(d.total_sell_qty)}</span>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface AlertRow {
  id: number;
  symbol: string;
  op: string;
  value: number;
  message: string;
  status: string;
  triggered_at: string | null;
}

export function AlertsPanel({ onNew }: { onNew: () => void }) {
  const qc = useQueryClient();
  const { symbol } = useActiveSymbol();
  const q = useQuery({ queryKey: ["alerts", "all"], queryFn: () => apiJson<AlertRow[]>("/api/alerts"), refetchInterval: 10_000 });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["alerts"] });
  const del = useMutation({ mutationFn: (id: number) => apiJson(`/api/alerts/${id}`, { method: "DELETE" }), onSuccess: refresh, onError: (e: Error) => toast.error(e.message) });
  const patch = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => apiJson(`/api/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  const rows = q.data ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b p-2">
        <span className="text-xs text-muted-foreground">{rows.filter((r) => r.status === "active").length} active</span>
        <Button size="xs" onClick={onNew}>
          <Bell className="h-3 w-3" /> Alert on {shortSymbol(symbol).slice(0, 12)}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 && <p className="p-3 text-xs text-muted-foreground">No alerts yet. Set one from here or with the bell in the toolbar.</p>}
        {rows.map((a) => (
          <div key={a.id} className="group flex items-start gap-2 border-b px-3 py-2 text-xs">
            <span className={cn("mt-1 h-2 w-2 shrink-0 rounded-full", a.status === "active" ? "bg-warning" : a.status === "triggered" ? "bg-profit" : "bg-muted-foreground")} />
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                {shortSymbol(a.symbol)} {a.op === "above" ? "≥" : "≤"} <span className="num">{fmtPrice(a.value)}</span>
              </p>
              <p className="truncate text-muted-foreground">{a.status === "triggered" && a.triggered_at ? `Triggered ${new Date(a.triggered_at).toLocaleString("en-IN")}` : a.message || a.status}</p>
            </div>
            <span className="flex gap-0.5 opacity-60 group-hover:opacity-100">
              {a.status === "active" ? (
                <button aria-label="Pause alert" className="rounded p-0.5 hover:bg-muted" onClick={() => patch.mutate({ id: a.id, status: "paused" })}>
                  <BellOff className="h-3.5 w-3.5" />
                </button>
              ) : (
                <button aria-label="Re-arm alert" className="rounded p-0.5 hover:bg-muted" onClick={() => patch.mutate({ id: a.id, status: "active" })}>
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              )}
              <button aria-label="Delete alert" className="rounded p-0.5 hover:bg-muted hover:text-loss" onClick={() => del.mutate(a.id)}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ObjectsPanel() {
  const { active, symbol } = useActiveSymbol();
  const cell = useTerminal((s) => s.layout.cells[s.layout.active]!);
  const drawings = useTerminal((s) => s.layout.drawings[symbol] ?? NO_DRAWINGS);
  const selected = useTerminal((s) => s.selected);
  const { setDrawings, select, setCell } = useTerminal.getState();
  const upd = (id: string, patch: Record<string, unknown>) => setDrawings(symbol, drawings.map((d) => (d.id === id ? { ...d, ...patch } : d)));
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto text-xs">
      <p className="border-b px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Drawings · {shortSymbol(symbol)}</p>
      {drawings.length === 0 && <p className="px-3 py-2 text-muted-foreground">Use the tools on the left to draw.</p>}
      {drawings.map((d) => (
        <div key={d.id} className={cn("group flex items-center gap-2 px-3 py-1.5 hover:bg-muted/60", selected?.id === d.id && "bg-primary/10")}>
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: d.color }} />
          <button className="min-w-0 flex-1 truncate text-left" onClick={() => select({ symbol, id: d.id })}>
            {TOOL_LABEL[d.type]}
            {d.text ? ` · ${d.text}` : ""}
          </button>
          <button aria-label={d.hidden ? "Show" : "Hide"} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => upd(d.id, { hidden: !d.hidden })}>
            {d.hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
          <button aria-label={d.locked ? "Unlock" : "Lock"} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => upd(d.id, { locked: !d.locked })}>
            {d.locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
          </button>
          <button aria-label="Delete drawing" className="rounded p-0.5 text-muted-foreground hover:text-loss" onClick={() => setDrawings(symbol, drawings.filter((x) => x.id !== d.id))}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <p className="mt-2 border-y px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Indicators</p>
      {cell.indicators.length === 0 && <p className="px-3 py-2 text-muted-foreground">None.</p>}
      {cell.indicators.map((i) => {
        const def = INDICATOR_BY_ID[i.id];
        if (!def) return null;
        return (
          <div key={i.uid} className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted/60">
            <span className="min-w-0 flex-1 truncate">{indicatorLabel(def, i.params)}</span>
            <button aria-label={i.visible ? "Hide" : "Show"} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => setCell(active, { indicators: cell.indicators.map((x) => (x.uid === i.uid ? { ...x, visible: !x.visible } : x)) })}>
              {i.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
            </button>
            <button aria-label="Remove indicator" className="rounded p-0.5 text-muted-foreground hover:text-loss" onClick={() => setCell(active, { indicators: cell.indicators.filter((x) => x.uid !== i.uid) })}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
