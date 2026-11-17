"use client";
import type { Schemas } from "@algo/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, KeyRound, Link2, Plus, Star, Trash2, TriangleAlert } from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/common";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { api, apiJson, unwrap } from "@/lib/api";
import { timeAgo } from "@/lib/format";

type Conn = Schemas["ConnectionOut"];

function AddDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const cat = useQuery({ queryKey: ["broker-catalog"], queryFn: () => unwrap(api.GET("/api/brokers/catalog")) });
  const [broker, setBroker] = React.useState<string | undefined>(undefined);
  const [creds, setCreds] = React.useState<Record<string, string>>({});
  const spec = cat.data?.find((b) => b.name === broker);
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/brokers/connections", { body: { broker: broker!, label: spec?.display_name ?? "", credentials: creds } })),
    onSuccess: () => {
      toast.success("Credentials stored encrypted — now log in to activate the session");
      void qc.invalidateQueries({ queryKey: ["broker-connections"] });
      onOpenChange(false);
      setCreds({});
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect a broker</DialogTitle>
          <DialogDescription>API credentials are encrypted with AES-256-GCM, bound to your account and never shown or logged again.</DialogDescription>
        </DialogHeader>
        <Field label="Broker">
          <Select value={broker} onValueChange={(b) => { setBroker(b); setCreds({}); }} placeholder="Choose broker" options={(cat.data ?? []).map((b) => ({ value: b.name, label: `${b.display_name} · ${b.auth_type.toUpperCase()}` }))} />
        </Field>
        {spec && (
          <div className="flex flex-col gap-2">
            {spec.credential_fields.map((f) => (
              <Field key={f.name} label={`${f.label}${f.required ? "" : " (optional)"}`}>
                <Input type={f.secret ? "password" : "text"} autoComplete="off" value={creds[f.name] ?? ""} onChange={(e) => setCreds({ ...creds, [f.name]: e.target.value })} />
              </Field>
            ))}
            <a className="flex items-center gap-1 text-2xs text-primary hover:underline" href={spec.docs_url} target="_blank" rel="noreferrer">
              <ExternalLink className="h-3 w-3" /> {spec.display_name} API docs
            </a>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!spec} loading={add.isPending} onClick={() => add.mutate()}>
            Save credentials
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LoginDialog({ conn, onClose }: { conn: Conn | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [totp, setTotp] = React.useState("");
  const m = useMutation({
    mutationFn: () => unwrap(api.POST("/api/brokers/connections/{conn_id}/login", { params: { path: { conn_id: conn!.id } }, body: { totp: totp || null } })),
    onSuccess: () => {
      toast.success(`${conn?.display_name} connected`);
      void qc.invalidateQueries({ queryKey: ["broker-connections"] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={!!conn} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Log in to {conn?.display_name}</DialogTitle>
          <DialogDescription>{conn?.auth_type === "token" ? "Validates the stored access token." : "Enter the current TOTP from your broker authenticator (skip if you stored a TOTP secret)."}</DialogDescription>
        </DialogHeader>
        {conn?.auth_type === "totp" && (
          <Field label="TOTP code">
            <Input inputMode="numeric" autoComplete="one-time-code" value={totp} onChange={(e) => setTotp(e.target.value)} placeholder="123456" />
          </Field>
        )}
        <DialogFooter>
          <Button loading={m.isPending} onClick={() => m.mutate()}>
            Log in
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function BrokerConnections() {
  const qc = useQueryClient();
  const params = useSearchParams();
  const [adding, setAdding] = React.useState(false);
  const [loginFor, setLoginFor] = React.useState<Conn | null>(null);
  const q = useQuery({ queryKey: ["broker-connections"], queryFn: () => unwrap(api.GET("/api/brokers/connections")) });
  React.useEffect(() => {
    const ok = params.get("connected");
    const err = params.get("error");
    if (ok) toast.success(`${ok} connected`);
    if (err) toast.error(`Broker login failed (${err.replace(/_/g, " ")})`);
  }, [params]);
  const del = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/brokers/connections/{conn_id}", { params: { path: { conn_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["broker-connections"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  const def = useMutation({
    mutationFn: (id: number) => unwrap(api.POST("/api/brokers/connections/{conn_id}/default", { params: { path: { conn_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["broker-connections"] }),
  });
  const connect = async (c: Conn) => {
    if (c.auth_type !== "oauth") return setLoginFor(c);
    try {
      const { url } = await apiJson<{ url: string }>(`/api/brokers/connections/${c.id}/oauth-url`);
      window.location.href = url;
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const rows = q.data ?? [];
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle>Connected brokers</CardTitle>
          <CardDescription className="mt-1">Upstox, Zerodha, Angel One, Dhan, Fyers, Kotak Neo, 5paisa, ICICI Breeze, Alice Blue, Shoonya. Paper trading needs no broker.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus /> Add broker
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {q.isLoading ? (
          <Skeleton className="h-20" />
        ) : rows.length === 0 ? (
          <EmptyState icon={Link2} title="No brokers connected" description="Live trading routes orders through your own broker account." />
        ) : (
          rows.map((c) => {
            const expSoon = c.token_expires_at && new Date(c.token_expires_at).getTime() - Date.now() < 3 * 3600_000;
            return (
              <div key={c.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-xs font-bold uppercase text-primary">{c.broker.slice(0, 2)}</div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {c.display_name}
                    {c.is_default && (
                      <Badge variant="default">
                        <Star className="h-3 w-3" /> default
                      </Badge>
                    )}
                  </div>
                  <div className="text-2xs text-muted-foreground">
                    {c.client_id || "—"} · {c.auth_type} · added {timeAgo(c.created_at)}
                  </div>
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  {c.status === "connected" ? (
                    <Badge variant={expSoon ? "warning" : "profit"} className="gap-1">
                      {expSoon ? <TriangleAlert className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
                      {expSoon ? `expires ${timeAgo(c.token_expires_at!).replace(" ago", "")}` : "connected"}
                    </Badge>
                  ) : (
                    <Badge variant={c.status === "error" || c.status === "expired" ? "loss" : "secondary"} title={c.status_message ?? undefined}>
                      {c.status}
                    </Badge>
                  )}
                  <Button size="sm" variant="outline" onClick={() => connect(c)}>
                    <KeyRound /> {c.status === "connected" ? "Re-login" : "Log in"}
                  </Button>
                  {!c.is_default && (
                    <Button size="sm" variant="ghost" onClick={() => def.mutate(c.id)}>
                      Make default
                    </Button>
                  )}
                  <Button size="icon-sm" variant="ghost" aria-label="Disconnect" className="text-muted-foreground hover:text-loss" onClick={() => confirm(`Disconnect ${c.display_name} and erase its credentials?`) && del.mutate(c.id)}>
                    <Trash2 />
                  </Button>
                </div>
              </div>
            );
          })
        )}
        <p className="text-2xs text-muted-foreground">Indian broker sessions expire daily (~03:30–06:00 IST); log in each trading day. Register this platform&apos;s static egress IP with your broker where required.</p>
      </CardContent>
      <AddDialog open={adding} onOpenChange={setAdding} />
      <LoginDialog conn={loginFor} onClose={() => setLoginFor(null)} />
    </Card>
  );
}
