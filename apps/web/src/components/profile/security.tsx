"use client";
import type { Schemas } from "@algo/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Laptop, ShieldCheck, ShieldOff } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import * as React from "react";
import { toast } from "sonner";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";

export function TwoFactorCard() {
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const [setup, setSetup] = React.useState<Schemas["TwoFASetupOut"] | null>(null);
  const [code, setCode] = React.useState("");
  const [recovery, setRecovery] = React.useState<string[] | null>(null);
  const refreshMe = async () => setUser(await unwrap(api.GET("/api/me")));
  const start = useMutation({ mutationFn: () => unwrap(api.POST("/api/auth/2fa/setup")), onSuccess: setSetup, onError: (e: Error) => toast.error(e.message) });
  const enable = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/2fa/enable", { body: { code } })),
    onSuccess: async (r) => {
      setRecovery(r.recovery_codes);
      setSetup(null);
      setCode("");
      await refreshMe();
      toast.success("Two-factor authentication enabled");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const disable = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/2fa/disable", { body: { code } })),
    onSuccess: async () => {
      setCode("");
      await refreshMe();
      toast.success("Two-factor authentication disabled — live trading is now blocked");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {user?.totp_enabled ? <ShieldCheck className="h-4 w-4 text-profit" /> : <ShieldOff className="h-4 w-4 text-warning" />} Two-factor authentication (TOTP)
        </CardTitle>
        <CardDescription>Required for live trading. Each live deployment and live order asks for a fresh code.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {recovery && (
          <div className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            <p className="mb-2 font-medium text-warning">Save these one-time recovery codes now — they won&apos;t be shown again.</p>
            <div className="grid grid-cols-2 gap-1 font-mono sm:grid-cols-4">
              {recovery.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
          </div>
        )}
        {user?.totp_enabled ? (
          <div className="flex flex-wrap items-end gap-2">
            <Badge variant="profit">enabled</Badge>
            <Field label="Code to disable">
              <Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" placeholder="123456" />
            </Field>
            <Button variant="outline" onClick={() => disable.mutate()} loading={disable.isPending}>
              Disable 2FA
            </Button>
          </div>
        ) : setup ? (
          <div className="flex flex-wrap items-start gap-4">
            <div className="rounded-lg bg-white p-2">
              <QRCodeSVG value={setup.otpauth_uri} size={148} />
            </div>
            <div className="flex flex-col gap-2 text-xs">
              <p>Scan with Google Authenticator, Authy or 1Password, or enter the key manually:</p>
              <code className="break-all rounded bg-muted px-2 py-1 font-mono">{setup.secret}</code>
              <Field label="6-digit code">
                <Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" />
              </Field>
              <Button onClick={() => enable.mutate()} loading={enable.isPending} disabled={code.length < 6}>
                Verify & enable
              </Button>
            </div>
          </div>
        ) : (
          <Button className="w-fit" onClick={() => start.mutate()} loading={start.isPending}>
            Set up 2FA
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function SessionsCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sessions"], queryFn: () => unwrap(api.GET("/api/auth/sessions")) });
  const revoke = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/auth/sessions/{session_id}", { params: { path: { session_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Active sessions</CardTitle>
        <CardDescription>Refresh tokens rotate on use; re-use of an old token revokes the whole session family.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {(q.data ?? []).map((s) => (
          <div key={s.id} className="flex items-center gap-3 rounded-md border p-2 text-xs">
            <Laptop className="h-4 w-4 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="truncate">{s.user_agent || "Unknown device"}</div>
              <div className="text-muted-foreground">
                {s.ip} · last used {s.last_used_at ? timeAgo(s.last_used_at) : "—"}
              </div>
            </div>
            {s.current ? (
              <Badge variant="profit">this device</Badge>
            ) : (
              <Button size="xs" variant="ghost" className="text-loss" onClick={() => revoke.mutate(s.id)}>
                Revoke
              </Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
