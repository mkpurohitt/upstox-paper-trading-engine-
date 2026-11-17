"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, ChevronDown, CircleAlert, Newspaper, OctagonX, Search, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Stat } from "@/components/common";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Checkbox, Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiJson, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { inr, istTime, shortDate, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const err = (e: Error) => toast.error(e instanceof ApiError ? e.message : "Request failed");

export function Overview() {
  const q = useQuery({ queryKey: ["admin-stats"], queryFn: () => apiJson<Any>("/api/admin/stats"), refetchInterval: 30_000 });
  const refresh = useMutation({ mutationFn: () => apiJson("/api/news/refresh", { method: "POST" }), onSuccess: () => toast.success("News refresh queued"), onError: err });
  const d = q.data;
  if (!d) return <Skeleton className="h-48" />;
  const subs = d.subscriptions as Record<string, number>;
  const deps = d.deployments_running as Record<string, number>;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        <Stat label="Users" value={d.users} hint={`+${d.new_users_today} today · ${d.active_users_7d} active 7d`} />
        <Stat label="Paid subscriptions" value={(subs.pro ?? 0) + (subs.elite ?? 0)} hint={`pro ${subs.pro ?? 0} · elite ${subs.elite ?? 0}`} />
        <Stat label="Revenue" value={inr(d.revenue_paise / 100, { compact: true })} hint="all time, captured" />
        <Stat label="Running strategies" value={Object.values(deps).reduce((a, b) => a + b, 0)} hint={`live ${deps.live ?? 0} · paper ${deps.paper ?? 0}`} tone={(deps.live ?? 0) > 0 ? "warning" : "default"} />
        <Stat label="Orders today" value={d.orders_today} />
        <Stat label="AI today" value={d.ai_queries_today} hint={`${d.llm_tokens_today.toLocaleString("en-IN")} tokens · $${d.llm_cost_today_usd}`} />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant={d.pending_reviews ? "warning" : "secondary"}>{d.pending_reviews} black-box review(s) pending</Badge>
        <Badge variant="outline">{d.rag_documents} knowledge documents</Badge>
        <Button size="sm" variant="outline" onClick={() => refresh.mutate()} loading={refresh.isPending}>
          <Newspaper /> Refresh news now
        </Button>
      </div>
    </div>
  );
}

export function Users() {
  const qc = useQueryClient();
  const me = useAuth((s) => s.user);
  const [q, setQ] = React.useState("");
  const [term, setTerm] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setTerm(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  const users = useQuery({ queryKey: ["admin-users", term], queryFn: () => apiJson<Any[]>(`/api/admin/users?limit=200${term ? `&q=${encodeURIComponent(term)}` : ""}`) });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Any }) => apiJson(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      toast.success("User updated");
      void qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: err,
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Users</CardTitle>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search email or name" className="h-8 w-64 pl-7 text-xs" />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {users.isLoading ? (
          <Skeleton className="m-4 h-40" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>User</TH>
                <TH>Plan</TH>
                <TH>Role</TH>
                <TH>Security</TH>
                <TH>Joined</TH>
                <TH>Last login</TH>
                <TH className="text-right">Status</TH>
              </TR>
            </THead>
            <TBody>
              {(users.data ?? []).map((u) => (
                <TR key={u.id} className={cn(!u.is_active && "opacity-60")}>
                  <TD>
                    <div className="text-xs font-medium">{u.full_name || "—"}</div>
                    <div className="text-2xs text-muted-foreground">{u.email}</div>
                    {u.deletion_requested_at && <Badge variant="loss" className="mt-0.5">deletion pending</Badge>}
                  </TD>
                  <TD>
                    <Select value={u.plan} onValueChange={(v) => patch.mutate({ id: u.id, body: { plan_code: v, note: "admin plan change" } })} className="h-7 w-24 text-xs" ariaLabel="Plan" options={["free", "pro", "elite"].map((p) => ({ value: p, label: p }))} />
                  </TD>
                  <TD>
                    <Select value={u.role} disabled={u.id === me?.id} onValueChange={(v) => patch.mutate({ id: u.id, body: { role: v } })} className="h-7 w-24 text-xs" ariaLabel="Role" options={[{ value: "user", label: "user" }, { value: "admin", label: "admin" }]} />
                  </TD>
                  <TD className="text-2xs">
                    <Badge variant={u.totp_enabled ? "profit" : "secondary"}>{u.totp_enabled ? "2FA" : "no 2FA"}</Badge> {u.kill_switch && <Badge variant="loss">killed</Badge>}
                  </TD>
                  <TD className="text-xs text-muted-foreground">{shortDate(u.created_at)}</TD>
                  <TD className="text-xs text-muted-foreground">{u.last_login_at ? timeAgo(u.last_login_at) : "never"}</TD>
                  <TD className="text-right">
                    <Button size="xs" variant={u.is_active ? "ghost" : "outline"} disabled={u.id === me?.id} onClick={() => confirm(`${u.is_active ? "Deactivate" : "Reactivate"} ${u.email}?`) && patch.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function Billing() {
  const subs = useQuery({ queryKey: ["admin-subs"], queryFn: () => apiJson<Any[]>("/api/admin/subscriptions") });
  const pays = useQuery({ queryKey: ["admin-pays"], queryFn: () => apiJson<Any[]>("/api/admin/payments") });
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Subscriptions</CardTitle>
        </CardHeader>
        <CardContent className="max-h-[520px] overflow-auto p-0 scrollbar-thin">
          <Table>
            <THead>
              <TR>
                <TH>User</TH>
                <TH>Plan</TH>
                <TH>Status</TH>
                <TH>Period end</TH>
              </TR>
            </THead>
            <TBody>
              {(subs.data ?? []).map((s) => (
                <TR key={s.id}>
                  <TD className="text-xs">{s.email}</TD>
                  <TD className="text-xs capitalize">{s.plan}</TD>
                  <TD>
                    <Badge variant={s.status === "active" ? "profit" : "secondary"}>{s.status}</Badge>
                    {s.cancel_at_period_end && <Badge variant="warning" className="ml-1">cancelling</Badge>}
                  </TD>
                  <TD className="text-xs text-muted-foreground">{s.current_period_end ? shortDate(s.current_period_end) : "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Payments</CardTitle>
        </CardHeader>
        <CardContent className="max-h-[520px] overflow-auto p-0 scrollbar-thin">
          <Table>
            <THead>
              <TR>
                <TH>User</TH>
                <TH className="text-right">Amount</TH>
                <TH>Status</TH>
                <TH>Order</TH>
                <TH>Date</TH>
              </TR>
            </THead>
            <TBody>
              {(pays.data ?? []).map((p) => (
                <TR key={p.id}>
                  <TD className="text-xs">{p.email}</TD>
                  <TD className="num text-right text-xs">{inr(p.amount_paise / 100, { decimals: 0 })}</TD>
                  <TD>
                    <Badge variant={p.status === "paid" ? "profit" : p.status === "failed" ? "loss" : "secondary"}>{p.status}</Badge>
                  </TD>
                  <TD className="max-w-[140px] truncate font-mono text-[10px] text-muted-foreground">{p.order_id}</TD>
                  <TD className="text-xs text-muted-foreground">{shortDate(p.created_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function Check({ name, c }: { name: string; c: Any }) {
  return (
    <div className="flex items-center gap-3 rounded-md border px-3 py-2 text-xs">
      {c.ok ? <CheckCircle2 className="h-4 w-4 text-profit" /> : <XCircle className="h-4 w-4 text-loss" />}
      <span className="w-28 font-medium capitalize">{name.replace(/_/g, " ")}</span>
      <span className="flex-1 truncate text-muted-foreground">{String(c.detail)}</span>
      <span className="num text-muted-foreground">{c.latency_ms} ms</span>
    </div>
  );
}

export function Health() {
  const q = useQuery({ queryKey: ["admin-health"], queryFn: () => apiJson<Any>("/api/admin/health"), refetchInterval: 20_000 });
  const d = q.data;
  if (!d) return <Skeleton className="h-64" />;
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" /> Services
            <Badge variant={d.status === "ok" ? "profit" : "loss"}>{d.status}</Badge>
            {d.global_kill_switch && <Badge variant="loss">global kill switch ON</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {Object.entries(d.checks as Record<string, Any>).map(([k, c]) => (
            <Check key={k} name={k} c={c} />
          ))}
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            {Object.entries(d.runtime as Record<string, unknown>).map(([k, v]) => (
              <div key={k} className="rounded-md bg-muted/40 px-2 py-1">
                <div className="text-2xs uppercase text-muted-foreground">{k === "uptime_s" ? "uptime" : k.replace(/_/g, " ")}</div>
                <div className="truncate font-medium">{k === "uptime_s" ? `${Math.round(Number(v) / 60)} min` : String(v ?? "—")}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <div className="flex flex-col gap-3">
        <Card>
          <CardHeader>
            <CardTitle>AI gateway</CardTitle>
            <CardDescription>
              {d.llm.configured ? "LLM configured" : "No LLM key configured — offline assistant in use"} · embeddings: {d.llm.embedder} · advice {d.llm.advice_enabled ? "ENABLED" : "disabled"}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-1.5">
            {(d.llm.providers as Any[]).map((p, i) => (
              <div key={p.provider} className="flex items-center gap-2 text-xs">
                <Badge variant={i === 0 ? "info" : "outline"}>{i === 0 ? "primary" : `fallback ${i}`}</Badge>
                <span className="font-medium">{p.provider}</span>
                <span className="truncate text-muted-foreground">
                  {p.cheap_model} / {p.strong_model}
                </span>
                <span className="ml-auto">{p.healthy ? <CheckCircle2 className="h-3.5 w-3.5 text-profit" /> : <CircleAlert className="h-3.5 w-3.5 text-loss" />}</span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Jobs & realtime</CardTitle>
            <CardDescription>
              Queue: {d.jobs.mode} · {d.realtime.ws_clients} WebSocket client(s), {d.realtime.channels} channel(s)
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1">
            {(d.jobs.registered as string[]).map((j) => (
              <Badge key={j} variant={(d.jobs.cron as string[]).includes(j) ? "info" : "outline"}>
                {j}
              </Badge>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function GlobalKillSwitch() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-kill"], queryFn: () => apiJson<Any>("/api/admin/kill-switch"), refetchInterval: 15_000 });
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [square, setSquare] = React.useState(false);
  const engaged = !!q.data?.engaged;
  const set = useMutation({
    mutationFn: () => apiJson<Any>("/api/admin/kill-switch", { method: "POST", body: JSON.stringify({ engaged: !engaged, square_off: square, reason }) }),
    onSuccess: (r) => {
      toast.success(r.engaged ? `Platform halted · ${r.deployments_stopped ?? 0} deployment(s) stopped` : "Platform trading resumed");
      setOpen(false);
      setReason("");
      void qc.invalidateQueries({ queryKey: ["admin-kill"] });
      void qc.invalidateQueries({ queryKey: ["admin-health"] });
    },
    onError: err,
  });
  return (
    <Card className={cn(engaged ? "border-loss/60 bg-loss/5" : "")}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <OctagonX className={cn("h-5 w-5", engaged ? "text-loss" : "text-muted-foreground")} /> Platform kill switch
          <Badge variant={engaged ? "loss" : "profit"}>{engaged ? "ENGAGED" : "off"}</Badge>
        </CardTitle>
        <CardDescription>
          Blocks every new order for every user (paper and live) and stops all running deployments. Users can still reduce positions through system square-offs. Every change is audited with your reason.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {q.data?.details?.at && (
          <p className="text-xs text-muted-foreground">
            Last change {istTime(q.data.details.at, true)} IST{q.data.details.reason ? ` · “${q.data.details.reason}”` : ""}
          </p>
        )}
        <Button variant={engaged ? "outline" : "destructive"} size="lg" onClick={() => setOpen(true)} className="self-start">
          {engaged ? "Release kill switch" : "Engage kill switch"}
        </Button>
      </CardContent>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{engaged ? "Resume platform trading?" : "Halt all trading on the platform?"}</DialogTitle>
            <DialogDescription>{engaged ? "New orders will be accepted again. Stopped deployments stay stopped until their owners restart them." : "All running deployments stop immediately and new orders are rejected."}</DialogDescription>
          </DialogHeader>
          <Field label="Reason (recorded in the audit log)">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. exchange outage / suspected runaway algo" />
          </Field>
          {!engaged && (
            <label className="flex items-center gap-2 text-xs">
              <Checkbox checked={square} onCheckedChange={(v) => setSquare(v === true)} /> Also square off every user&apos;s open positions
            </label>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant={engaged ? "default" : "destructive"} disabled={reason.trim().length < 3} loading={set.isPending} onClick={() => set.mutate()}>
              {engaged ? "Release" : "Engage"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

export function AuditViewer() {
  const [action, setAction] = React.useState("");
  const [actor, setActor] = React.useState("all");
  const [userId, setUserId] = React.useState("");
  const [open, setOpen] = React.useState<number | null>(null);
  const params = new URLSearchParams({ limit: "200" });
  if (action.trim()) params.set("action", action.trim());
  if (actor !== "all") params.set("actor", actor);
  if (/^\d+$/.test(userId)) params.set("user_id", userId);
  const q = useQuery({ queryKey: ["admin-audit", params.toString()], queryFn: () => apiJson<Any[]>(`/api/admin/audit?${params}`) });
  const verify = useMutation({
    mutationFn: () => apiJson<Any>("/api/admin/audit/verify"),
    onSuccess: (r) => (r.ok ? toast.success(`Hash chain intact · ${r.entries} entries verified in ${r.seconds}s`) : toast.error(`Chain broken at entry #${r.first_bad_id}`)),
    onError: err,
  });
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-end justify-between gap-2">
        <div>
          <CardTitle>Audit trail</CardTitle>
          <CardDescription>Append-only and hash-chained; updates and deletes are blocked at the database.</CardDescription>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Action prefix">
            <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="order., ai., admin." className="h-8 w-40 text-xs" />
          </Field>
          <Field label="Actor">
            <Select value={actor} onValueChange={setActor} className="h-8 w-28 text-xs" options={["all", "user", "admin", "system", "agent", "runner"].map((a) => ({ value: a, label: a }))} />
          </Field>
          <Field label="User ID">
            <Input value={userId} onChange={(e) => setUserId(e.target.value)} className="h-8 w-20 text-xs" inputMode="numeric" />
          </Field>
          <Button size="sm" variant="outline" onClick={() => verify.mutate()} loading={verify.isPending}>
            <ShieldCheck /> Verify chain
          </Button>
        </div>
      </CardHeader>
      <CardContent className="max-h-[600px] overflow-auto p-0 scrollbar-thin">
        {q.isLoading ? (
          <Skeleton className="m-4 h-40" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>#</TH>
                <TH>Time (IST)</TH>
                <TH>Actor</TH>
                <TH>User</TH>
                <TH>Action</TH>
                <TH>Entity</TH>
                <TH>Hash</TH>
              </TR>
            </THead>
            <TBody>
              {(q.data ?? []).map((r) => (
                <React.Fragment key={r.id}>
                  <TR className="cursor-pointer" onClick={() => setOpen(open === r.id ? null : r.id)}>
                    <TD className="num text-xs text-muted-foreground">{r.id}</TD>
                    <TD className="whitespace-nowrap text-xs">{istTime(r.ts, true)}</TD>
                    <TD>
                      <Badge variant={r.actor === "admin" ? "warning" : r.actor === "system" ? "info" : "outline"}>{r.actor}</Badge>
                    </TD>
                    <TD className="num text-xs">{r.user_id ?? "—"}</TD>
                    <TD className="font-mono text-xs">{r.action}</TD>
                    <TD className="text-xs text-muted-foreground">{r.entity_type ? `${r.entity_type}#${r.entity_id}` : "—"}</TD>
                    <TD className="font-mono text-[10px] text-muted-foreground">
                      {r.hash.slice(0, 10)}… <ChevronDown className={cn("inline h-3 w-3 transition-transform", open === r.id && "rotate-180")} />
                    </TD>
                  </TR>
                  {open === r.id && (
                    <TR>
                      <TD colSpan={7}>
                        <pre className="max-h-48 overflow-auto rounded bg-muted/50 p-2 font-mono text-2xs scrollbar-thin">{JSON.stringify({ ...r.payload, ip: r.ip }, null, 2)}</pre>
                      </TD>
                    </TR>
                  )}
                </React.Fragment>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function Reviews() {
  const qc = useQueryClient();
  const [status, setStatus] = React.useState("pending");
  const q = useQuery({ queryKey: ["admin-reviews", status], queryFn: () => apiJson<Any[]>(`/api/admin/strategies/review?status=${status}`) });
  const [target, setTarget] = React.useState<{ id: number; name: string; decision: "approve" | "reject" } | null>(null);
  const [note, setNote] = React.useState("");
  const review = useMutation({
    mutationFn: () => apiJson(`/api/admin/strategies/${target!.id}/review`, { method: "POST", body: JSON.stringify({ decision: target!.decision, note }) }),
    onSuccess: () => {
      toast.success("Review recorded and the owner notified");
      setTarget(null);
      setNote("");
      void qc.invalidateQueries({ queryKey: ["admin-reviews"] });
      void qc.invalidateQueries({ queryKey: ["admin-stats"] });
    },
    onError: err,
  });
  return (
    <Card>
      <CardHeader className="flex-row items-end justify-between gap-2">
        <div>
          <CardTitle>Black-box strategy reviews</CardTitle>
          <CardDescription>
            Black-box (undisclosed-logic) algos may only be offered by SEBI-registered Research Analysts. Verify the RA registration number on the SEBI intermediary register before approving.
          </CardDescription>
        </div>
        <Select value={status} onValueChange={setStatus} className="h-8 w-32 text-xs" options={["pending", "approved", "rejected"].map((s) => ({ value: s, label: s }))} />
      </CardHeader>
      <CardContent className="p-0">
        {(q.data ?? []).length === 0 ? (
          <p className="p-4 text-xs text-muted-foreground">Nothing {status}.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Strategy</TH>
                <TH>Owner</TH>
                <TH>RA number</TH>
                <TH>Updated</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {(q.data ?? []).map((s) => (
                <TR key={s.id}>
                  <TD>
                    <div className="text-xs font-medium">{s.name}</div>
                    <div className="line-clamp-1 text-2xs text-muted-foreground">{s.description}</div>
                  </TD>
                  <TD className="text-xs">{s.owner}</TD>
                  <TD className="font-mono text-xs">{s.provider_ra_number}</TD>
                  <TD className="text-xs text-muted-foreground">{timeAgo(s.updated_at)}</TD>
                  <TD className="text-right">
                    {status === "pending" && (
                      <>
                        <Button size="xs" variant="outline" onClick={() => setTarget({ id: s.id, name: s.name, decision: "approve" })}>
                          <ShieldCheck className="h-3 w-3" /> Approve
                        </Button>
                        <Button size="xs" variant="ghost" className="text-loss" onClick={() => setTarget({ id: s.id, name: s.name, decision: "reject" })}>
                          <ShieldX className="h-3 w-3" /> Reject
                        </Button>
                      </>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
      <Dialog open={!!target} onOpenChange={(o) => !o && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {target?.decision === "approve" ? "Approve" : "Reject"} “{target?.name}”
            </DialogTitle>
            <DialogDescription>The note is sent to the strategy owner and stored in the audit log.</DialogDescription>
          </DialogHeader>
          <Field label="Note">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={target?.decision === "approve" ? "RA registration verified on SEBI register" : "Reason for rejection"} />
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setTarget(null)}>
              Cancel
            </Button>
            <Button variant={target?.decision === "approve" ? "default" : "destructive"} disabled={note.trim().length < 3} loading={review.isPending} onClick={() => review.mutate()}>
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
