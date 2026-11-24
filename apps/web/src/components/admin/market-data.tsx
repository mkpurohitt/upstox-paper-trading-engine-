"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, KeyRound, PauseCircle, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { apiJson } from "@/lib/api";

interface Status {
  name: string;
  live: boolean;
  source: "admin" | "env" | "none";
  last_error: string | null;
  saved: boolean;
  enabled: boolean;
  token_hint: string | null;
  expires_at: string | null;
  expired: boolean;
  verified_at: string | null;
  verified_nifty_ltp: number | null;
  env_token_configured: boolean;
  data_mode: string;
}

const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }) + " IST" : "—");

export function MarketDataPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-market-data"], queryFn: () => apiJson<Status>("/api/admin/market-data"), refetchInterval: 30_000 });
  const [token, setToken] = React.useState("");
  const done = (s: Status, msg: string) => {
    qc.setQueryData(["admin-market-data"], s);
    void qc.invalidateQueries({ queryKey: ["chart-source"] });
    void qc.invalidateQueries({ queryKey: ["chart-bars"] });
    toast.success(msg);
  };
  const save = useMutation({
    mutationFn: (body: { token?: string; enabled: boolean }) => apiJson<Status>("/api/admin/market-data", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (s, body) => {
      setToken("");
      done(s, body.enabled ? `Live Upstox data is on${s.verified_nifty_ltp ? ` · NIFTY ${s.verified_nifty_ltp.toLocaleString("en-IN")}` : ""}` : "Live data paused; using simulated data");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const clear = useMutation({
    mutationFn: () => apiJson<Status>("/api/admin/market-data", { method: "DELETE" }),
    onSuccess: (s) => done(s, "Saved token removed"),
    onError: (e: Error) => toast.error(e.message),
  });
  const s = q.data;
  if (!s) return <Skeleton className="h-80" />;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Live market data (Upstox)
            <Badge variant={s.live ? "profit" : "warning"}>{s.live ? "Live · Upstox" : "Simulated"}</Badge>
          </CardTitle>
          <CardDescription>
            Charts, quotes, option chains, the screener, paper fills and strategy runners all use this feed. Changes apply immediately — no restart.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <dl className="grid grid-cols-[160px_1fr] gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">Provider</dt>
            <dd>
              {s.name} {s.source === "admin" ? "(token saved here)" : s.source === "env" ? "(token from the server environment)" : ""}
            </dd>
            <dt className="text-muted-foreground">Saved token</dt>
            <dd className="font-mono">{s.token_hint ?? "none"}</dd>
            <dt className="text-muted-foreground">Expires</dt>
            <dd className={s.expired ? "font-medium text-loss" : ""}>
              {s.expires_at ? fmtTime(s.expires_at) : "—"} {s.expired && "· expired, paste a new token"}
            </dd>
            <dt className="text-muted-foreground">Last verified</dt>
            <dd>
              {fmtTime(s.verified_at)}
              {s.verified_nifty_ltp ? ` · NIFTY 50 ${s.verified_nifty_ltp.toLocaleString("en-IN")}` : ""}
            </dd>
            {s.env_token_configured && s.source !== "admin" && (
              <>
                <dt className="text-muted-foreground">Environment</dt>
                <dd>A token is set in the server environment (DATA_MODE={s.data_mode}).</dd>
              </>
            )}
          </dl>
          {s.last_error && <p className="rounded-md bg-loss/10 px-3 py-2 text-xs text-loss">{s.last_error}</p>}
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate({ token: token.trim() || undefined, enabled: true });
            }}
          >
            <label htmlFor="upstox-token" className="text-xs font-medium">
              Upstox access token or analytics token
            </label>
            <textarea
              id="upstox-token"
              className="min-h-[84px] w-full resize-y rounded-md border bg-background p-2 font-mono text-xs"
              placeholder="eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOi…"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            <p className="text-[11px] text-muted-foreground">Verified against Upstox before it is saved, then encrypted (AES-256-GCM). It is never shown again — only its last characters.</p>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={save.isPending} disabled={!token.trim() && !s.saved}>
                <KeyRound /> {token.trim() ? "Verify & go live" : "Turn on live data"}
              </Button>
              {s.saved && s.enabled && (
                <Button type="button" variant="outline" onClick={() => save.mutate({ enabled: false })} loading={save.isPending}>
                  <PauseCircle /> Pause (use simulated)
                </Button>
              )}
              {s.saved && (
                <Button type="button" variant="ghost" className="text-loss" onClick={() => confirm("Remove the saved Upstox token?") && clear.mutate()} loading={clear.isPending}>
                  <Trash2 /> Remove token
                </Button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Getting a token</CardTitle>
          <CardDescription>Either kind works for market data.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-xs leading-relaxed">
          <div>
            <p className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 className="h-3.5 w-3.5 text-profit" /> Analytics token (recommended)
            </p>
            <p className="text-muted-foreground">
              Long-lived and read-only (market data only, no trading). Generate it from your Upstox developer account&apos;s apps page and paste it here.
            </p>
          </div>
          <div>
            <p className="font-medium">Daily access token</p>
            <p className="text-muted-foreground">
              From an Upstox app&apos;s login flow (API key + secret → authorization code → token). It expires every day at 03:30 IST, so it must be replaced each morning.
            </p>
          </div>
          <div>
            <p className="font-medium">Or set it on the server</p>
            <p className="text-muted-foreground">
              In <code className="rounded bg-muted px-1">.env</code>: <code className="rounded bg-muted px-1">DATA_MODE=live</code> and <code className="rounded bg-muted px-1">UPSTOX_ACCESS_TOKEN=…</code>, then restart. A token saved here takes precedence.
            </p>
          </div>
          <a className="inline-flex items-center gap-1 text-primary hover:underline" href="https://upstox.com/developer/api-documentation/" target="_blank" rel="noreferrer">
            Upstox API documentation <ExternalLink className="h-3 w-3" />
          </a>
          <p className="rounded-md bg-muted/60 p-2 text-muted-foreground">
            Without a token everything keeps working on the built-in simulated market, and every chart is labelled <b>SIMULATED</b> so it is never mistaken for live prices.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
