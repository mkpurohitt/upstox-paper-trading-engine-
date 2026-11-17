"use client";
import type { Schemas } from "@algo/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { EmptyState, Pnl, Stat } from "@/components/common";
import { Field } from "@/components/dashboard";
import { SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useRealtime, useTicks } from "@/hooks/use-realtime";
import { api, ApiError, unwrap } from "@/lib/api";
import { compactInr, inr, istTime, num } from "@/lib/format";
import { cn } from "@/lib/utils";

type OrderOut = Schemas["OrderOut"];

const STATUS_VARIANT: Record<string, "profit" | "loss" | "warning" | "info" | "secondary"> = {
  complete: "profit", rejected: "loss", cancelled: "secondary", open: "info", trigger_pending: "warning", pending: "warning",
};

export function useOrders(params: { mode?: string; deployment_id?: number; today?: boolean } = {}) {
  const qc = useQueryClient();
  const key = ["orders", params];
  const q = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/orders", { params: { query: { ...params, limit: 200 } } })) });
  useRealtime({ channel: "orders" }, (f) => {
    const o = f.data as OrderOut;
    if (params.deployment_id && o.deployment_id !== params.deployment_id) return;
    qc.setQueryData<OrderOut[]>(key, (prev) => {
      const list = prev ? [...prev] : [];
      const i = list.findIndex((x) => x.id === o.id);
      if (i >= 0) list[i] = { ...list[i]!, ...o };
      else list.unshift(o);
      return list;
    });
    void qc.invalidateQueries({ queryKey: ["positions"] });
    void qc.invalidateQueries({ queryKey: ["funds"] });
  });
  return q;
}

export function OrderTicket({ mode = "paper", defaultSymbol = "NSE:SBIN" }: { mode?: "paper" | "live"; defaultSymbol?: string }) {
  const qc = useQueryClient();
  const [symbol, setSymbol] = React.useState(defaultSymbol);
  const [side, setSide] = React.useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = React.useState(1);
  const [type, setType] = React.useState<"MARKET" | "LIMIT" | "SL" | "SL-M">("MARKET");
  const [product, setProduct] = React.useState<"MIS" | "CNC" | "NRML">("MIS");
  const [price, setPrice] = React.useState<number | "">("");
  const [trigger, setTrigger] = React.useState<number | "">("");
  const ltp = useTicks([symbol])[symbol]?.ltp;
  const m = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/orders", {
          body: { symbol, side, quantity: qty, order_type: type, product, price: price === "" ? null : price, trigger_price: trigger === "" ? null : trigger, mode },
        }),
      ),
    onSuccess: (rows) => {
      const r = rows[rows.length - 1]!;
      toast[r.status === "rejected" ? "error" : "success"](`${side} ${qty} ${symbol}: ${r.status}${r.average_price ? ` @ ${num(r.average_price)}` : ""}`);
      void qc.invalidateQueries({ queryKey: ["positions"] });
    },
    onError: (e: Error) => {
      const d = e instanceof ApiError ? (e.details as { decision?: { rule?: string } } | undefined) : undefined;
      toast.error(`Rejected${d?.decision?.rule ? ` (${d.decision.rule})` : ""}: ${e.message}`);
    },
  });
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Order ticket</CardTitle>
        <Badge variant={mode === "live" ? "loss" : "info"}>{mode}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-xs">
            {symbol}
          </Badge>
          <span className="num text-sm font-semibold">{ltp ? num(ltp) : ""}</span>
          <SymbolSearch className="flex-1" onPick={setSymbol} placeholder="Change symbol" />
        </div>
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
          {(["BUY", "SELL"] as const).map((s) => (
            <button key={s} type="button" onClick={() => setSide(s)} className={cn("rounded-md py-1.5 text-sm font-semibold", side === s ? (s === "BUY" ? "bg-profit text-white" : "bg-loss text-white") : "text-muted-foreground")}>
              {s}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Quantity">
            <Input type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
          </Field>
          <Field label="Product">
            <Select value={product} onValueChange={(v) => setProduct(v as "MIS")} options={["MIS", "CNC", "NRML"].map((x) => ({ value: x, label: x }))} />
          </Field>
          <Field label="Type">
            <Select value={type} onValueChange={(v) => setType(v as "MARKET")} options={["MARKET", "LIMIT", "SL", "SL-M"].map((x) => ({ value: x, label: x }))} />
          </Field>
          <Field label="Price">
            <Input type="number" step="0.05" disabled={type === "MARKET" || type === "SL-M"} value={price} onChange={(e) => setPrice(e.target.value === "" ? "" : Number(e.target.value))} />
          </Field>
          {(type === "SL" || type === "SL-M") && (
            <Field label="Trigger">
              <Input type="number" step="0.05" value={trigger} onChange={(e) => setTrigger(e.target.value === "" ? "" : Number(e.target.value))} />
            </Field>
          )}
        </div>
        <Button variant={side === "BUY" ? "profit" : "loss"} loading={m.isPending} onClick={() => m.mutate()}>
          {side} {qty} · ≈ {ltp ? compactInr(ltp * qty) : "—"}
        </Button>
        <p className="text-2xs text-muted-foreground">Every order passes the pre-trade risk engine. Paper fills use live prices with {mode === "paper" ? "5 bps" : "real"} slippage.</p>
      </CardContent>
    </Card>
  );
}

export function OrdersBlotter({ mode, deploymentId, today = true, compact = false }: { mode?: string; deploymentId?: number; today?: boolean; compact?: boolean }) {
  const qc = useQueryClient();
  const q = useOrders({ mode, deployment_id: deploymentId, today });
  const cancel = useMutation({
    mutationFn: (id: number) => unwrap(api.POST("/api/orders/{order_id}/cancel", { params: { path: { order_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["orders"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  if (q.isLoading) return <Skeleton className="h-40" />;
  const rows = q.data ?? [];
  if (!rows.length) return <EmptyState title="No orders" description={today ? "Orders placed today appear here in real time." : undefined} />;
  return (
    <div className={cn("overflow-auto scrollbar-thin", compact ? "max-h-72" : "max-h-[480px]")}>
      <Table>
        <THead>
          <TR>
            <TH>Time</TH>
            <TH>Symbol</TH>
            <TH>Side</TH>
            <TH className="text-right">Qty</TH>
            <TH className="text-right">Price</TH>
            <TH>Type</TH>
            <TH>Status</TH>
            <TH>Algo-ID</TH>
            <TH />
          </TR>
        </THead>
        <TBody>
          {rows.map((o) => (
            <TR key={o.id} title={o.status_message ?? undefined}>
              <TD className="text-muted-foreground">{istTime(o.created_at)}</TD>
              <TD className="font-medium">{o.symbol}</TD>
              <TD>
                <span className={o.side === "BUY" ? "text-profit" : "text-loss"}>{o.side}</span>
              </TD>
              <TD className="text-right">
                {o.filled_quantity}/{o.quantity}
              </TD>
              <TD className="text-right">{num(o.average_price ?? o.price)}</TD>
              <TD className="text-xs text-muted-foreground">
                {o.order_type} · {o.product}
              </TD>
              <TD>
                <Badge variant={STATUS_VARIANT[o.status] ?? "secondary"}>{o.status.replace("_", " ")}</Badge>
              </TD>
              <TD className="font-mono text-2xs text-muted-foreground">{o.algo_id}</TD>
              <TD>
                {["open", "trigger_pending"].includes(o.status) && (
                  <Button size="icon-sm" variant="ghost" aria-label="Cancel order" onClick={() => cancel.mutate(o.id)}>
                    <X />
                  </Button>
                )}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

export function PositionsTable({ mode = "paper", connectionId }: { mode?: string; connectionId?: number }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["positions", mode, connectionId],
    queryFn: () => unwrap(api.GET("/api/positions", { params: { query: { mode, connection_id: connectionId } } })),
    refetchInterval: 10_000,
  });
  const rows = (q.data ?? []).filter((p) => p.quantity !== 0 || p.realised_pnl !== 0);
  const live = useTicks(rows.filter((p) => p.quantity).map((p) => p.symbol));
  const sq = useMutation({
    mutationFn: () => unwrap(api.POST("/api/positions/square-off", { params: { query: { mode } } })),
    onSuccess: (r) => {
      toast.success(`Placed ${r.length} square-off order(s)`);
      void qc.invalidateQueries({ queryKey: ["positions"] });
    },
  });
  if (q.isLoading) return <Skeleton className="h-32" />;
  if (!rows.length) return <EmptyState title="No positions" description="Open positions and today's realised P&L show here." />;
  let total = 0;
  const body = rows.map((p) => {
    const ltp = live[p.symbol]?.ltp ?? p.last_price;
    const unreal = p.quantity ? (ltp - p.average_price) * p.quantity : 0;
    total += unreal + p.realised_pnl;
    return { ...p, ltp, unreal };
  });
  return (
    <div className="flex flex-col gap-2">
      <Table>
        <THead>
          <TR>
            <TH>Symbol</TH>
            <TH>Product</TH>
            <TH className="text-right">Qty</TH>
            <TH className="text-right">Avg</TH>
            <TH className="text-right">LTP</TH>
            <TH className="text-right">Unrealised</TH>
            <TH className="text-right">Realised</TH>
          </TR>
        </THead>
        <TBody>
          {body.map((p) => (
            <TR key={`${p.symbol}-${p.product}`}>
              <TD className="font-medium">{p.symbol}</TD>
              <TD className="text-xs text-muted-foreground">{p.product}</TD>
              <TD className={cn("text-right", p.quantity > 0 ? "text-profit" : p.quantity < 0 ? "text-loss" : "")}>{p.quantity}</TD>
              <TD className="text-right">{num(p.average_price)}</TD>
              <TD className="text-right">{num(p.ltp)}</TD>
              <TD className="text-right">
                <Pnl value={p.unreal} />
              </TD>
              <TD className="text-right">
                <Pnl value={p.realised_pnl} />
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <div className="flex items-center justify-between text-sm">
        <span>
          Total P&L: <Pnl value={total} className="font-semibold" />
        </span>
        <Button size="sm" variant="outline" className="text-loss" loading={sq.isPending} onClick={() => confirm("Square off all open MIS/NRML positions?") && sq.mutate()}>
          Square off all
        </Button>
      </div>
    </div>
  );
}

export function FundsStrip({ mode = "paper" }: { mode?: string }) {
  const q = useQuery({ queryKey: ["funds", mode], queryFn: () => unwrap(api.GET("/api/funds", { params: { query: { mode } } })), refetchInterval: 15_000 });
  const f = q.data;
  return (
    <div className="grid grid-cols-3 gap-2">
      <Stat label="Account value" value={f ? inr(f.total, { decimals: 0 }) : "—"} />
      <Stat label="Available margin" value={f ? inr(f.available, { decimals: 0 }) : "—"} tone="profit" />
      <Stat label="Margin used" value={f ? inr(f.used, { decimals: 0 }) : "—"} />
    </div>
  );
}

export { CardHeader, CardTitle };
