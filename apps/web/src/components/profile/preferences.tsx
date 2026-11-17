"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Download, Eye, Moon, Monitor, Send, ShieldOff, Sun, Trash2, Undo2 } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";
import { toast } from "sonner";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton, Switch } from "@/components/ui/misc";
import { api, apiFetch, apiJson, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { shortDate, timeAgo } from "@/lib/format";
import { usePrefs } from "@/lib/prefs";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- notifications

const EVENTS: [string, string, string][] = [
  ["order_fills", "Order fills & rejections", "Every fill, rejection and risk-engine block"],
  ["deployment_status", "Strategy status", "Deployments starting, stopping, erroring or squaring off"],
  ["risk", "Risk alerts", "Daily loss limit, kill switch and margin warnings"],
  ["screen_alerts", "Screener alerts", "New stocks matching a saved screen"],
  ["daily_summary", "Daily P&L summary", "End-of-day recap at 15:45 IST"],
];

type Prefs = Record<string, unknown> & { events?: Record<string, boolean> };

export function NotificationPrefs() {
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const qc = useQueryClient();
  const [p, setP] = React.useState<Prefs>(() => ({ email: true, telegram: false, whatsapp: false, telegram_chat_id: "", ...(user?.notification_prefs ?? {}) }));
  const events = (p.events ?? {}) as Record<string, boolean>;
  const save = useMutation({
    mutationFn: (prefs: Prefs) => unwrap(api.PATCH("/api/me", { body: { notification_prefs: prefs } })),
    onSuccess: (u) => {
      setUser(u);
      toast.success("Notification preferences saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const test = useMutation({
    mutationFn: () =>
      apiJson<{ channels_sent: string[] }>("/api/notifications/test", {
        method: "POST",
        body: JSON.stringify({ channels: ["in_app", ...(["email", "telegram", "whatsapp"] as const).filter((c) => p[c])] }),
      }),
    onSuccess: (n) => {
      toast.success(n.channels_sent.length ? `Sent via in-app + ${n.channels_sent.join(", ")}` : "Sent in-app (external channels need server configuration)");
      void qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
  const set = (k: string, v: unknown) => setP((x) => ({ ...x, [k]: v }));
  const history = useQuery({ queryKey: ["notifications"], queryFn: () => unwrap(api.GET("/api/notifications", { params: { query: { limit: 20 } } })) });
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-primary" /> Channels
          </CardTitle>
          <CardDescription>In-app notifications are always on. Strategy deployments can also choose channels individually.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <label className="flex items-center justify-between text-sm">
            <span>
              Email <span className="text-xs text-muted-foreground">· {user?.email}</span>
            </span>
            <Switch checked={!!p.email} onCheckedChange={(v) => set("email", v)} />
          </label>
          <div className="flex flex-col gap-2">
            <label className="flex items-center justify-between text-sm">
              Telegram
              <Switch checked={!!p.telegram} onCheckedChange={(v) => set("telegram", v)} />
            </label>
            {!!p.telegram && (
              <Field label="Telegram chat ID (message the bot, then paste your chat ID)">
                <Input value={String(p.telegram_chat_id ?? "")} onChange={(e) => set("telegram_chat_id", e.target.value.trim())} placeholder="123456789" />
              </Field>
            )}
          </div>
          <label className="flex items-center justify-between text-sm">
            <span>
              WhatsApp <span className="text-xs text-muted-foreground">· {user?.phone || "add a mobile number in Account"}</span>
            </span>
            <Switch checked={!!p.whatsapp} disabled={!user?.phone} onCheckedChange={(v) => set("whatsapp", v)} />
          </label>
          <div className="mt-2 flex flex-col gap-2 border-t pt-3">
            <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">Notify me about</p>
            {EVENTS.map(([k, label, hint]) => (
              <label key={k} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {label}
                  <span className="block text-2xs text-muted-foreground">{hint}</span>
                </span>
                <Switch checked={events[k] ?? k !== "daily_summary"} onCheckedChange={(v) => set("events", { ...events, [k]: v })} />
              </label>
            ))}
          </div>
          <div className="flex gap-2">
            <Button onClick={() => save.mutate(p)} loading={save.isPending}>
              Save preferences
            </Button>
            <Button variant="outline" onClick={() => test.mutate()} loading={test.isPending}>
              <Send /> Send test
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Recent notifications</CardTitle>
        </CardHeader>
        <CardContent className="max-h-[520px] overflow-y-auto scrollbar-thin">
          {!history.data ? (
            <Skeleton className="h-40" />
          ) : history.data.items.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nothing yet.</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {history.data.items.map((n) => (
                <li key={n.id} className="py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{n.kind}</Badge>
                    <span className={cn("font-medium", !n.read_at && "text-primary")}>{n.title}</span>
                    <span className="ml-auto text-2xs text-muted-foreground">{timeAgo(n.created_at)}</span>
                  </div>
                  {n.body ? <p className="mt-0.5 text-muted-foreground">{n.body}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- appearance

export function AppearancePrefs() {
  const { theme, setTheme } = useTheme();
  const setUser = useAuth((s) => s.setUser);
  const { colourBlind, setColourBlind, density, setDensity } = usePrefs();
  const choose = (t: "dark" | "light" | "system") => {
    setTheme(t);
    void unwrap(api.PATCH("/api/me", { body: { theme: t } })).then(setUser).catch(() => undefined);
  };
  const opts = [
    { id: "dark", label: "Dark", icon: Moon },
    { id: "light", label: "Light", icon: Sun },
    { id: "system", label: "System", icon: Monitor },
  ] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-primary" /> Appearance & accessibility
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Theme">
          {opts.map((o) => (
            <button
              key={o.id}
              type="button"
              role="radio"
              aria-checked={theme === o.id}
              onClick={() => choose(o.id)}
              className={cn("flex items-center gap-2 rounded-lg border p-3 text-sm transition-colors", theme === o.id ? "border-primary bg-primary/5" : "hover:bg-accent")}
            >
              <o.icon className="h-4 w-4" /> {o.label}
            </button>
          ))}
        </div>
        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Colour-blind safe P&amp;L palette
            <span className="block text-2xs text-muted-foreground">Blue for gains and orange for losses instead of green/red. Arrows and signs are always shown too.</span>
          </span>
          <Switch checked={colourBlind} onCheckedChange={setColourBlind} />
        </label>
        <div className="flex gap-3 text-xs">
          <span className="text-profit">▲ +₹1,250.00 gain</span>
          <span className="text-loss">▼ −₹830.00 loss</span>
        </div>
        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Compact density
            <span className="block text-2xs text-muted-foreground">Tighter tables and cards for large screens</span>
          </span>
          <Switch checked={density === "compact"} onCheckedChange={(v) => setDensity(v ? "compact" : "comfortable")} />
        </label>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- privacy (DPDP)

interface ConsentsT {
  current: { purpose: string; description: string; required: boolean; granted: boolean; version: string; updated_at: string | null }[];
  ledger: { purpose: string; granted: boolean; version: string; created_at: string }[];
}

export function PrivacyPanel() {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const q = useQuery({ queryKey: ["consents"], queryFn: () => apiJson<ConsentsT>("/api/account/consents") });
  const toggle = useMutation({
    mutationFn: (v: { purpose: string; granted: boolean }) => apiJson<ConsentsT>("/api/account/consents", { method: "POST", body: JSON.stringify(v) }),
    onSuccess: (d) => qc.setQueryData(["consents"], d),
    onError: (e: Error) => toast.error(e.message),
  });
  const [del, setDel] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [reason, setReason] = React.useState("");
  const reload = () => void unwrap(api.GET("/api/me")).then(setUser).catch(() => undefined);
  const remove = useMutation({
    mutationFn: () => apiJson<{ message: string }>("/api/account/delete", { method: "POST", body: JSON.stringify({ confirm_email: email, reason }) }),
    onSuccess: (r) => {
      toast.success(r.message);
      setDel(false);
      reload();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const cancel = useMutation({
    mutationFn: () => apiJson<{ message: string }>("/api/account/delete/cancel", { method: "POST" }),
    onSuccess: (r) => {
      toast.success(r.message);
      reload();
    },
  });
  const [exporting, setExporting] = React.useState(false);
  const exportData = async () => {
    setExporting(true);
    try {
      const res = await apiFetch("/api/account/export");
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `algodesk-export-${user?.id}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setExporting(false);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Consents</CardTitle>
          <CardDescription>Under the Digital Personal Data Protection Act 2023 you can review and withdraw optional consents at any time. Every change is recorded in an append-only ledger.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {!q.data ? (
            <Skeleton className="h-32" />
          ) : (
            q.data.current.map((c) => (
              <label key={c.purpose} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
                <span>
                  {c.description}
                  <span className="block text-2xs text-muted-foreground">
                    {c.required ? "Required to use the service" : "Optional"} · v{c.version}
                    {c.updated_at ? ` · updated ${shortDate(c.updated_at)}` : ""}
                  </span>
                </span>
                <Switch checked={c.granted} disabled={c.required} onCheckedChange={(v) => toggle.mutate({ purpose: c.purpose, granted: v })} aria-label={c.description} />
              </label>
            ))
          )}
        </CardContent>
      </Card>
      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Download className="h-4 w-4 text-primary" /> Export your data
            </CardTitle>
            <CardDescription>A JSON file with your profile, consents, strategies, backtests, orders, trades, chats, notifications and audit entries. Broker credentials are never included.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => void exportData()} loading={exporting}>
              <Download /> Download export
            </Button>
          </CardContent>
        </Card>
        <Card className="border-loss/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-loss">
              <Trash2 className="h-4 w-4" /> Delete account
            </CardTitle>
            <CardDescription>
              Trading stops immediately; personal data is erased after a 7-day grace period. Orders, trades and the audit trail are kept (pseudonymised) where exchange and SEBI record-keeping rules require it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {user?.deletion_requested_at ? (
              <div className="flex flex-col gap-2 text-sm">
                <p className="flex items-center gap-2 text-loss">
                  <ShieldOff className="h-4 w-4" /> Deletion requested {shortDate(user.deletion_requested_at)}
                </p>
                <Button variant="outline" onClick={() => cancel.mutate()} loading={cancel.isPending}>
                  <Undo2 /> Cancel deletion
                </Button>
              </div>
            ) : (
              <Button variant="destructive" onClick={() => setDel(true)}>
                <Trash2 /> Delete my account
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
      {q.data && q.data.ledger.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Consent history</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col divide-y text-xs">
              {q.data.ledger.slice(0, 15).map((l, i) => (
                <li key={i} className="flex gap-3 py-1">
                  <span className="w-24 text-muted-foreground">{shortDate(l.created_at)}</span>
                  <span className="w-40">{l.purpose.replace(/_/g, " ")}</span>
                  <Badge variant={l.granted ? "profit" : "secondary"}>{l.granted ? "granted" : "withdrawn"}</Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      <Dialog open={del} onOpenChange={setDel}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete your account?</DialogTitle>
            <DialogDescription>
              This engages your kill switch (stopping all strategies and squaring off paper positions) and schedules erasure of your personal data in 7 days. You can cancel during that time.
            </DialogDescription>
          </DialogHeader>
          <Field label={`Type your email (${user?.email}) to confirm`}>
            <Input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Reason (optional)">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDel(false)}>
              Keep my account
            </Button>
            <Button variant="destructive" disabled={email.trim().toLowerCase() !== (user?.email ?? "").toLowerCase()} loading={remove.isPending} onClick={() => remove.mutate()}>
              Delete account
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
