"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, CreditCard, IdCard, Save } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress, Skeleton } from "@/components/ui/misc";
import { api, ApiError, apiJson, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { inr, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function AccountDetails() {
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const [name, setName] = React.useState(user?.full_name ?? "");
  const [phone, setPhone] = React.useState(user?.phone ?? "");
  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/me", { body: { full_name: name.trim(), phone: phone.trim() || null } })),
    onSuccess: (u) => {
      setUser(u);
      toast.success("Profile saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (!user) return <Skeleton className="h-40" />;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Account details</CardTitle>
        <CardDescription>Member since {shortDate(user.created_at)} · plan {user.plan}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        <Field label="Full name">
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </Field>
        <Field label="Email">
          <Input value={user.email} disabled />
        </Field>
        <Field label="Mobile (for WhatsApp alerts)">
          <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 98xxxxxxxx" inputMode="tel" />
        </Field>
        <div className="flex items-end">
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim()}>
            <Save /> Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function KycCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["kyc"], queryFn: () => apiJson<{ status: string; pan_last4: string | null; note: string }>("/api/account/kyc") });
  const [pan, setPan] = React.useState("");
  const [nm, setNm] = React.useState("");
  const submit = useMutation({
    mutationFn: () => apiJson("/api/account/kyc", { method: "POST", body: JSON.stringify({ pan, name_on_pan: nm }) }),
    onSuccess: () => {
      setPan("");
      toast.success("KYC details submitted");
      void qc.invalidateQueries({ queryKey: ["kyc"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <IdCard className="h-4 w-4 text-primary" /> KYC
          {q.data && <Badge variant={q.data.status === "submitted" ? "info" : q.data.status === "verified" ? "profit" : "secondary"}>{q.data.status.replace("_", " ")}</Badge>}
        </CardTitle>
        <CardDescription>{q.data?.note}</CardDescription>
      </CardHeader>
      <CardContent>
        {q.data?.pan_last4 ? (
          <p className="flex items-center gap-2 text-sm">
            <BadgeCheck className="h-4 w-4 text-profit" /> PAN ending <span className="font-mono">{q.data.pan_last4}</span> on file
          </p>
        ) : (
          <form
            className="grid gap-3 sm:grid-cols-3"
            onSubmit={(e) => {
              e.preventDefault();
              submit.mutate();
            }}
          >
            <Field label="PAN">
              <Input value={pan} onChange={(e) => setPan(e.target.value.toUpperCase().slice(0, 10))} placeholder="ABCDE1234F" autoComplete="off" className="font-mono" />
            </Field>
            <Field label="Name on PAN">
              <Input value={nm} onChange={(e) => setNm(e.target.value)} />
            </Field>
            <div className="flex items-end">
              <Button type="submit" disabled={!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan) || nm.trim().length < 2} loading={submit.isPending}>
                Submit
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- subscription

interface PlanT { code: string; name: string; price_paise: number; interval: string; limits: Record<string, number>; features: string[] }
interface SubT {
  plan: PlanT;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  limits: Record<string, number>;
  usage: Record<string, number>;
  payments: { id: number; plan: string | null; amount_paise: number; status: string; method: string | null; razorpay_order_id: string | null; created_at: string; paid_at: string | null }[];
  razorpay: { mode: "test" | "live" | "simulated"; key_id: string | null };
}
interface CheckoutT { mode: string; order_id?: string; amount?: number; currency?: string; key_id?: string; name?: string; description?: string; prefill?: Record<string, string>; effective?: string }

declare global {
  interface Window {
    Razorpay?: new (opts: Record<string, unknown>) => { open: () => void; on: (ev: string, cb: (r: unknown) => void) => void };
  }
}

function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load Razorpay checkout"));
    document.body.appendChild(s);
  });
}

const USAGE: [string, string, string][] = [
  ["AI questions today", "ai_queries_today", "ai_queries_per_day"],
  ["Backtests today", "backtests_today", "backtests_per_day"],
  ["Live strategies", "live_strategies", "live_strategies"],
  ["Paper strategies", "paper_strategies", "paper_strategies"],
];

export function SubscriptionPanel() {
  const qc = useQueryClient();
  const setUser = useAuth((s) => s.setUser);
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => apiJson<PlanT[]>("/api/billing/plans") });
  const sub = useQuery({ queryKey: ["subscription"], queryFn: () => apiJson<SubT>("/api/billing/subscription") });
  const [sim, setSim] = React.useState<CheckoutT | null>(null);
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["subscription"] });
    void unwrap(api.GET("/api/me")).then(setUser).catch(() => undefined);
  };
  const checkout = useMutation({
    mutationFn: (code: string) => apiJson<CheckoutT>("/api/billing/checkout", { method: "POST", body: JSON.stringify({ plan_code: code }) }),
    onSuccess: async (c) => {
      if (c.mode === "downgrade") {
        toast.success(`Downgrade scheduled for ${c.effective ? shortDate(c.effective) : "the end of the period"}`);
        return done();
      }
      if (c.mode === "activated") return done();
      if (c.mode === "simulated") return setSim(c);
      await loadRazorpay();
      const rz = new window.Razorpay!({
        key: c.key_id,
        amount: c.amount,
        currency: c.currency,
        name: c.name,
        description: c.description,
        order_id: c.order_id,
        prefill: c.prefill,
        theme: { color: "#7c6cf5" },
        handler: async (resp: Record<string, string>) => {
          try {
            await apiJson("/api/billing/verify", { method: "POST", body: JSON.stringify(resp) });
            toast.success("Payment successful — plan activated");
          } catch (e) {
            toast.error((e as Error).message);
          }
          done();
        },
      });
      rz.on("payment.failed", () => toast.error("Payment failed or was cancelled"));
      rz.open();
    },
    onError: (e: Error) => toast.error(e instanceof ApiError ? e.message : "Checkout failed"),
  });
  const simulate = useMutation({
    mutationFn: (outcome: "success" | "failure") => apiJson<{ message: string }>("/api/billing/simulate", { method: "POST", body: JSON.stringify({ order_id: sim?.order_id, outcome }) }),
    onSuccess: (r) => {
      toast.success(r.message);
      setSim(null);
      done();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const cancelResume = useMutation({
    mutationFn: (what: "cancel" | "resume") => apiJson<{ message: string }>(`/api/billing/${what}`, { method: "POST" }),
    onSuccess: (r) => {
      toast.success(r.message);
      done();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const s = sub.data;
  if (!s || !plans.data) return <Skeleton className="h-96" />;
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-4 w-4 text-primary" /> {s.plan.name} plan
              {s.cancel_at_period_end && <Badge variant="warning">ends {s.current_period_end ? shortDate(s.current_period_end) : ""}</Badge>}
            </CardTitle>
            <CardDescription>
              {s.plan.price_paise ? `${inr(s.plan.price_paise / 100, { decimals: 0 })} / month` : "Free forever"}
              {s.current_period_end && !s.cancel_at_period_end ? ` · renews ${shortDate(s.current_period_end)}` : ""}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={s.razorpay.mode === "live" ? "profit" : "warning"}>Razorpay: {s.razorpay.mode}</Badge>
            {s.plan.price_paise > 0 &&
              (s.cancel_at_period_end ? (
                <Button size="sm" variant="outline" onClick={() => cancelResume.mutate("resume")}>
                  Resume
                </Button>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => confirm("Cancel at the end of the current period?") && cancelResume.mutate("cancel")}>
                  Cancel plan
                </Button>
              ))}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          {USAGE.map(([label, used, lim]) => {
            const u = s.usage[used] ?? 0;
            const l = s.limits[lim] ?? 0;
            return (
              <div key={label} className="flex flex-col gap-1">
                <div className="flex justify-between text-xs">
                  <span>{label}</span>
                  <span className="num text-muted-foreground">
                    {u} / {l}
                  </span>
                </div>
                <Progress value={l ? Math.min(100, (u / l) * 100) : 0} className={cn(l && u / l > 0.9 && "[&>div]:bg-loss")} />
              </div>
            );
          })}
        </CardContent>
      </Card>
      <div className="grid gap-3 md:grid-cols-3">
        {plans.data.map((p) => {
          const current = p.code === s.plan.code;
          return (
            <Card key={p.code} className={cn(current && "ring-1 ring-primary")}>
              <CardHeader>
                <CardTitle>{p.name}</CardTitle>
                <CardDescription>
                  <span className="text-xl font-semibold text-foreground">{p.price_paise ? inr(p.price_paise / 100, { decimals: 0 }) : "₹0"}</span> / {p.interval}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
                  {p.features.map((f) => (
                    <li key={f} className="flex gap-1.5">
                      <BadgeCheck className="mt-px h-3.5 w-3.5 shrink-0 text-profit" /> {f}
                    </li>
                  ))}
                </ul>
                <Button
                  variant={current ? "outline" : p.price_paise > s.plan.price_paise ? "default" : "ghost"}
                  disabled={current && !s.cancel_at_period_end}
                  loading={checkout.isPending && checkout.variables === p.code}
                  onClick={() => checkout.mutate(p.code)}
                >
                  {current ? "Current plan" : p.price_paise > s.plan.price_paise ? `Upgrade to ${p.name}` : `Switch to ${p.name}`}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Payment history</CardTitle>
        </CardHeader>
        <CardContent>
          {s.payments.length === 0 ? (
            <p className="text-xs text-muted-foreground">No payments yet.</p>
          ) : (
            <ul className="flex flex-col divide-y text-xs">
              {s.payments.map((p) => (
                <li key={p.id} className="flex items-center gap-3 py-1.5">
                  <span className="w-20 text-muted-foreground">{shortDate(p.created_at)}</span>
                  <span className="w-16 capitalize">{p.plan}</span>
                  <span className="num w-20">{inr(p.amount_paise / 100, { decimals: 0 })}</span>
                  <Badge variant={p.status === "paid" ? "profit" : p.status === "failed" ? "loss" : "secondary"}>{p.status}</Badge>
                  <span className="truncate font-mono text-[10px] text-muted-foreground">{p.razorpay_order_id}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Dialog open={!!sim} onOpenChange={(o) => !o && setSim(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Test checkout</DialogTitle>
            <DialogDescription>
              Razorpay keys are not configured, so this environment simulates the payment. Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (test keys start with rzp_test_) to use real Razorpay test mode.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg bg-muted/40 p-3 text-sm">
            {sim?.description} · <span className="font-semibold">{inr((sim?.amount ?? 0) / 100, { decimals: 0 })}</span>
            <div className="font-mono text-2xs text-muted-foreground">{sim?.order_id}</div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => simulate.mutate("failure")}>
              Simulate failure
            </Button>
            <Button onClick={() => simulate.mutate("success")} loading={simulate.isPending}>
              Simulate successful payment
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
