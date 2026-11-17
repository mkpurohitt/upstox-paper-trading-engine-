"use client";
import type { Schemas } from "@algo/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ChevronDown, Pause, Play, Radio, Rocket, Square, Undo2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { Disclaimer, EmptyState, PageHeader, Pnl, Stat } from "@/components/common";
import { FundsStrip, OrdersBlotter, OrderTicket, PositionsTable } from "@/components/trading/widgets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRealtime } from "@/hooks/use-realtime";
import { api, unwrap } from "@/lib/api";
import { istTime, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

type Dep = Schemas["DeploymentOut"];
type Log = Schemas["DeploymentLogOut"];

const STATUS: Record<string, "profit" | "warning" | "secondary" | "loss" | "info"> = {
  running: "profit", paused: "warning", stopped: "secondary", squared_off: "secondary", error: "loss", pending: "info",
};
const LEVEL_CLASS: Record<string, string> = { error: "text-loss", risk: "text-warning", order: "text-info", signal: "text-primary" };

function Logs({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["dep-logs", id], queryFn: () => unwrap(api.GET("/api/deployments/{dep_id}/logs", { params: { path: { dep_id: id }, query: { limit: 200 } } })) });
  const [live, setLive] = React.useState<Log[]>([]);
  useRealtime({ channel: "deployments" }, (f) => {
    const d = f.data as { type: string; deployment_id: number; level: string; message: string; ts: string; data: Record<string, unknown> };
    if (d.type === "log" && d.deployment_id === id) setLive((l) => [{ id: -Date.now(), ts: d.ts, level: d.level, message: d.message, data: d.data }, ...l].slice(0, 200));
  });
  const rows = [...live, ...(q.data ?? [])];
  if (q.isLoading) return <Skeleton className="h-32" />;
  return (
    <div className="max-h-64 overflow-auto rounded-md bg-muted/30 p-2 font-mono text-2xs scrollbar-thin" role="log" aria-live="polite">
      {rows.length === 0 && <p className="text-muted-foreground">No log lines yet.</p>}
      {rows.map((l) => (
        <div key={l.id} className="flex gap-2 py-0.5">
          <span className="shrink-0 text-muted-foreground">{istTime(l.ts, true)}</span>
          <span className={cn("w-12 shrink-0 uppercase", LEVEL_CLASS[l.level] ?? "text-muted-foreground")}>{l.level}</span>
          <span className="break-all">{l.message}</span>
        </div>
      ))}
    </div>
  );
}

function DeploymentCard({ d, pnl, focus }: { d: Dep; pnl?: { pnl: number; open_positions: number }; focus: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(focus);
  const act = useMutation({
    mutationFn: async (action: "pause" | "resume" | "stop" | "square-off") => {
      const path = { params: { path: { dep_id: d.id } } } as const;
      if (action === "pause") return unwrap(api.POST("/api/deployments/{dep_id}/pause", path));
      if (action === "resume") return unwrap(api.POST("/api/deployments/{dep_id}/resume", path));
      if (action === "stop") return unwrap(api.POST("/api/deployments/{dep_id}/stop", { params: { path: { dep_id: d.id }, query: { square_off: true } } }));
      return unwrap(api.POST("/api/deployments/{dep_id}/square-off", path));
    },
    onSuccess: (_, a) => {
      toast.success(`Deployment ${a.replace("-", " ")} done`);
      void qc.invalidateQueries({ queryKey: ["deployments"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const total = pnl?.pnl ?? d.pnl_realised + d.pnl_unrealised;
  const active = ["running", "paused"].includes(d.status);
  return (
    <Card className={cn(focus && "ring-1 ring-primary")}>
      <CardContent className="flex flex-col gap-3 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", d.status === "running" ? "animate-pulse bg-profit" : "bg-muted-foreground")} />
          <Link href={`/build/${d.strategy_id}`} className="font-semibold hover:text-primary">
            {d.name}
          </Link>
          <Badge variant={d.mode === "live" ? "loss" : d.mode === "paper" ? "info" : "secondary"}>{d.mode.toUpperCase()}</Badge>
          <Badge variant={STATUS[d.status] ?? "secondary"}>{d.status.replace("_", " ")}</Badge>
          <span className="text-2xs text-muted-foreground">
            v{d.strategy_version} · {d.broker} · ×{d.multiplier} · {(d.symbols ?? []).slice(0, 3).join(", ")}
            {(d.symbols ?? []).length > 3 ? "…" : ""}
          </span>
          <span className="ml-auto text-right">
            <Pnl value={total} className="text-lg font-semibold" />
            <span className="block text-2xs text-muted-foreground">{pnl ? `${pnl.open_positions} open position(s)` : d.started_at ? `started ${timeAgo(d.started_at)}` : ""}</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {d.status === "running" && (
            <Button size="sm" variant="outline" onClick={() => act.mutate("pause")}>
              <Pause /> Pause
            </Button>
          )}
          {d.status === "paused" && (
            <Button size="sm" variant="outline" onClick={() => act.mutate("resume")}>
              <Play /> Resume
            </Button>
          )}
          {active && (
            <>
              <Button size="sm" variant="outline" onClick={() => act.mutate("square-off")}>
                <Undo2 /> Square off
              </Button>
              <Button size="sm" variant="destructive" onClick={() => confirm(`Stop "${d.name}" and square off its positions?`) && act.mutate("stop")}>
                <Square /> Stop
              </Button>
            </>
          )}
          <span className="font-mono text-2xs text-muted-foreground">{d.algo_id}</span>
          {d.error && <span className="text-2xs text-loss">{d.error}</span>}
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setOpen(!open)} aria-expanded={open}>
            Details <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
          </Button>
        </div>
        {open && (
          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Logs</h3>
              <Logs id={d.id} />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Orders</h3>
              <OrdersBlotter deploymentId={d.id} today={false} compact />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Inner() {
  const params = useSearchParams();
  const focus = Number(params.get("focus") ?? 0);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["deployments"], queryFn: () => unwrap(api.GET("/api/deployments")), refetchInterval: 20_000 });
  const [pnl, setPnl] = React.useState<Record<number, { pnl: number; open_positions: number }>>({});
  useRealtime({ channel: "deployments" }, (f) => {
    const d = f.data as { type: string; deployment_id: number; pnl?: number; open_positions?: number };
    if (d.type === "pnl") setPnl((p) => ({ ...p, [d.deployment_id]: { pnl: d.pnl ?? 0, open_positions: d.open_positions ?? 0 } }));
    if (d.type === "status") void qc.invalidateQueries({ queryKey: ["deployments"] });
  });
  const rows = q.data ?? [];
  const active = rows.filter((d) => ["running", "paused"].includes(d.status));
  const past = rows.filter((d) => !["running", "paused"].includes(d.status));
  const totalPnl = active.reduce((a, d) => a + (pnl[d.id]?.pnl ?? d.pnl_realised + d.pnl_unrealised), 0);
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        icon={Radio}
        title="Live"
        description="Running strategies, paper trading desk and order flow — all orders pass the risk engine."
        actions={
          <Button asChild>
            <Link href="/build">
              <Rocket /> Deploy a strategy
            </Link>
          </Button>
        }
      />
      <Tabs defaultValue="strategies">
        <TabsList>
          <TabsTrigger value="strategies">Strategies ({active.length})</TabsTrigger>
          <TabsTrigger value="desk">Paper trading desk</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="strategies" className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Running" value={active.filter((d) => d.status === "running").length} />
            <Stat label="Paused" value={active.filter((d) => d.status === "paused").length} />
            <Stat label="Live (real money)" value={active.filter((d) => d.mode === "live").length} tone={active.some((d) => d.mode === "live") ? "loss" : "default"} />
            <Stat label="Combined P&L" value={<Pnl value={totalPnl} />} />
          </div>
          {q.isLoading ? (
            <Skeleton className="h-32" />
          ) : active.length === 0 ? (
            <EmptyState icon={Radio} title="Nothing running" description="Deploy a strategy from the Build page in paper, live or notify-only mode." />
          ) : (
            active.map((d, i) => (
              <motion.div key={d.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                <DeploymentCard d={d} pnl={pnl[d.id]} focus={d.id === focus} />
              </motion.div>
            ))
          )}
        </TabsContent>
        <TabsContent value="desk">
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="flex flex-col gap-3">
              <OrderTicket mode="paper" />
            </div>
            <div className="flex flex-col gap-3 lg:col-span-2">
              <FundsStrip mode="paper" />
              <Card>
                <CardHeader>
                  <CardTitle>Positions</CardTitle>
                </CardHeader>
                <CardContent>
                  <PositionsTable mode="paper" />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Today&apos;s orders</CardTitle>
                </CardHeader>
                <CardContent>
                  <OrdersBlotter mode="paper" />
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="history" className="flex flex-col gap-3">
          {past.length === 0 ? <EmptyState title="No past deployments" /> : past.map((d) => <DeploymentCard key={d.id} d={d} focus={false} />)}
        </TabsContent>
      </Tabs>
      <Disclaimer className="mt-4" />
    </div>
  );
}

export default function DeploymentsPage() {
  return (
    <React.Suspense>
      <Inner />
    </React.Suspense>
  );
}
