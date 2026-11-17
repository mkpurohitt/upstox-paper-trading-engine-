"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bell, FlaskConical, Radio, Rocket, ShieldAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { Disclaimer } from "@/components/common";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { api, ApiError, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useBuilder } from "@/lib/builder-store";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

type Mode = "paper" | "live" | "notify";
const MODES: { id: Mode; label: string; icon: typeof Radio; description: string }[] = [
  { id: "paper", label: "Paper", icon: FlaskConical, description: "Simulated fills on live prices — no money at risk." },
  { id: "live", label: "Live", icon: Radio, description: "Real orders through your connected broker. Requires 2FA." },
  { id: "notify", label: "Notify only", icon: Bell, description: "Signals as alerts (in-app, email, Telegram, WhatsApp). No orders." },
];

export function DeployPanel() {
  const router = useRouter();
  const { strategyId, version, dsl, dirty } = useBuilder();
  const user = useAuth((s) => s.user);
  const [mode, setMode] = React.useState<Mode>("paper");
  const [connectionId, setConnectionId] = React.useState<string | undefined>(undefined);
  const [capital, setCapital] = React.useState(1_000_000);
  const [multiplier, setMultiplier] = React.useState(1);
  const [limits, setLimits] = React.useState({ max_loss_per_day: 10000, max_orders_per_min: 30, max_position_value: 500000, max_lots: 5 });
  const [channels, setChannels] = React.useState<string[]>(["in_app"]);
  const [confirm, setConfirm] = React.useState(false);
  const [ack, setAck] = React.useState(false);
  const [totp, setTotp] = React.useState("");

  const conns = useQuery({ queryKey: ["broker-connections"], queryFn: () => unwrap(api.GET("/api/brokers/connections")) });
  const connected = (conns.data ?? []).filter((c) => c.status === "connected");
  React.useEffect(() => {
    if (!connectionId && connected[0]) setConnectionId(String(connected[0].id));
  }, [connected, connectionId]);

  const deploy = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/deployments", {
          body: {
            strategy_id: strategyId!,
            mode,
            connection_id: mode === "live" && connectionId ? Number(connectionId) : null,
            multiplier,
            capital,
            risk_limits: limits,
            notify_channels: channels as ("in_app" | "email" | "telegram" | "whatsapp")[],
            totp_code: mode === "live" ? totp : null,
            acknowledge_risk: ack,
          },
        }),
      ),
    onSuccess: (d) => {
      toast.success(`Deployed "${d.name}" (${d.mode})`);
      router.push(`/deployments?focus=${d.id}`);
    },
    onError: (e: Error) => toast.error(e instanceof ApiError ? e.message : "Deploy failed"),
  });

  if (!strategyId) return <p className="text-sm text-muted-foreground">Save the strategy before deploying.</p>;
  const liveBlocked = mode === "live" && (!user?.totp_enabled || connected.length === 0);
  const broker = connected.find((c) => String(c.id) === connectionId);

  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Deploy {dsl.name}</CardTitle>
          <CardDescription>
            Version v{version}
            {dirty && " (unsaved changes will NOT be deployed — save first)"} · runs the same DSL as your backtests.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Execution mode">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={mode === m.id}
                onClick={() => setMode(m.id)}
                className={cn("flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors", mode === m.id ? "border-primary bg-primary/5" : "hover:bg-accent")}
              >
                <span className="flex items-center gap-2 text-sm font-semibold">
                  <m.icon className={cn("h-4 w-4", m.id === "live" ? "text-loss" : "text-primary")} /> {m.label}
                </span>
                <span className="text-2xs text-muted-foreground">{m.description}</span>
              </button>
            ))}
          </div>
          {mode === "live" && (
            <div className="flex flex-col gap-2 rounded-lg border border-loss/30 bg-loss/5 p-3 text-xs">
              {!user?.totp_enabled && (
                <p className="flex items-center gap-1.5 text-loss">
                  <ShieldAlert className="h-4 w-4" /> Two-factor authentication is required for live trading.{" "}
                  <Link href="/profile?tab=security" className="underline">
                    Enable 2FA
                  </Link>
                </p>
              )}
              {connected.length === 0 ? (
                <p className="text-loss">
                  No connected broker.{" "}
                  <Link href="/profile?tab=brokers" className="underline">
                    Connect a broker
                  </Link>
                </p>
              ) : (
                <Field label="Broker">
                  <Select value={connectionId} onValueChange={setConnectionId} options={connected.map((c) => ({ value: String(c.id), label: `${c.display_name} · ${c.client_id}` }))} />
                </Field>
              )}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Capital allocated (₹)">
              <Input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
            </Field>
            <Field label="Multiplier (× sizing)">
              <Input type="number" min={1} max={50} value={multiplier} onChange={(e) => setMultiplier(Math.max(1, Number(e.target.value)))} />
            </Field>
            <Field label="Max loss / day (₹)">
              <Input type="number" value={limits.max_loss_per_day} onChange={(e) => setLimits({ ...limits, max_loss_per_day: Number(e.target.value) })} />
            </Field>
            <Field label="Max orders / min">
              <Input type="number" value={limits.max_orders_per_min} onChange={(e) => setLimits({ ...limits, max_orders_per_min: Number(e.target.value) })} />
            </Field>
            <Field label="Max position value (₹)">
              <Input type="number" value={limits.max_position_value} onChange={(e) => setLimits({ ...limits, max_position_value: Number(e.target.value) })} />
            </Field>
            <Field label="Max lots / order">
              <Input type="number" value={limits.max_lots} onChange={(e) => setLimits({ ...limits, max_lots: Number(e.target.value) })} />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <span className="text-muted-foreground">Alerts:</span>
            {(["in_app", "email", "telegram", "whatsapp"] as const).map((c) => (
              <label key={c} className="flex items-center gap-1.5">
                <Checkbox checked={channels.includes(c)} onCheckedChange={(v) => setChannels(v ? [...channels, c] : channels.filter((x) => x !== c))} />
                {c.replace("_", "-")}
              </label>
            ))}
          </div>
          <div className="flex justify-end">
            <Button onClick={() => setConfirm(true)} disabled={liveBlocked} variant={mode === "live" ? "destructive" : "default"}>
              <Rocket /> Review & deploy
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-profit" /> Safeguards
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs text-muted-foreground">
          <p>Every order passes the pre-trade risk engine: kill switches, exchange/instrument allow-lists, quantity, lot and position caps, orders/minute, the SEBI per-second order threshold and your daily loss limit.</p>
          <p>Orders are tagged with the strategy ID and an Algo-ID placeholder (replaced by the exchange-assigned ID after empanelment) and recorded in an immutable audit log.</p>
          <p>Use the kill switch in the top bar to halt everything instantly.</p>
          <Disclaimer kind="trading" />
        </CardContent>
      </Card>

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Rocket className="h-5 w-5 text-primary" /> Confirm deployment
            </DialogTitle>
            <DialogDescription>Review the parameters. You can pause, stop or square off at any time.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-lg bg-muted/40 p-3 text-xs">
            <span className="text-muted-foreground">Strategy</span>
            <span className="font-medium">
              {dsl.name} · v{version}
            </span>
            <span className="text-muted-foreground">Mode</span>
            <span>
              <Badge variant={mode === "live" ? "loss" : mode === "paper" ? "info" : "secondary"}>{mode.toUpperCase()}</Badge>
            </span>
            <span className="text-muted-foreground">Broker</span>
            <span>{mode === "live" ? broker?.display_name ?? "—" : mode === "paper" ? "Paper (simulated)" : "—"}</span>
            <span className="text-muted-foreground">Instruments</span>
            <span className="truncate">{dsl.kind === "options" ? `${dsl.universe?.underlying} options (${dsl.legs?.length} legs)` : (dsl.universe?.symbols ?? []).join(", ")}</span>
            <span className="text-muted-foreground">Capital / multiplier</span>
            <span>
              {inr(capital, { decimals: 0 })} × {multiplier}
            </span>
            <span className="text-muted-foreground">Max loss / day</span>
            <span className="text-loss">{inr(limits.max_loss_per_day, { decimals: 0 })}</span>
            <span className="text-muted-foreground">Orders / min · lots</span>
            <span>
              {limits.max_orders_per_min} · {limits.max_lots}
            </span>
            <span className="text-muted-foreground">Algo-ID</span>
            <span className="font-mono">ALGO-PENDING-S{strategyId}</span>
          </div>
          {mode === "live" && (
            <Field label="2FA code (step-up for live trading)">
              <Input inputMode="numeric" autoComplete="one-time-code" placeholder="123456" value={totp} onChange={(e) => setTotp(e.target.value)} />
            </Field>
          )}
          <label className="flex items-start gap-2 text-xs">
            <Checkbox checked={ack} onCheckedChange={(v) => setAck(v === true)} className="mt-0.5" />
            <span>
              I understand algorithmic trading carries substantial risk, that past/backtested performance does not guarantee results, and that I am responsible for this deployment{mode === "live" ? " and all orders placed with real money" : ""}.
            </span>
          </label>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button variant={mode === "live" ? "destructive" : "default"} disabled={!ack || (mode === "live" && totp.length < 6)} loading={deploy.isPending} onClick={() => deploy.mutate()}>
              Deploy {mode === "live" ? "LIVE" : mode}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
