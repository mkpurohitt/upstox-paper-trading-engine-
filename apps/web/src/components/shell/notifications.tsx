"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bell, BellRing, CheckCheck, Info, Radio, Settings, ShieldAlert } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/misc";
import { useRealtime } from "@/hooks/use-realtime";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const ICON: Record<string, typeof Info> = { risk: ShieldAlert, deployment: Radio, order: Radio, alert: BellRing, error: AlertTriangle };

export function NotificationsBell() {
  const qc = useQueryClient();
  const authed = useAuth((s) => !!s.token);
  const [open, setOpen] = React.useState(false);
  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => unwrap(api.GET("/api/notifications", { params: { query: { limit: 20 } } })),
    enabled: authed,
    refetchInterval: 120_000,
  });
  useRealtime(authed ? { channel: "notifications" } : null, (f) => {
    const d = f.data as { title?: string; body?: string; kind?: string };
    void qc.invalidateQueries({ queryKey: ["notifications"] });
    if (d?.title) toast(d.title, { description: d.body?.slice(0, 140), icon: <Bell className="h-4 w-4" /> });
  });
  const readAll = useMutation({
    mutationFn: () => unwrap(api.POST("/api/notifications/read-all")),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const read = (id: number) =>
    void unwrap(api.POST("/api/notifications/{notification_id}/read", { params: { path: { notification_id: id } } })).then(() =>
      qc.invalidateQueries({ queryKey: ["notifications"] }),
    );
  const unread = q.data?.unread ?? 0;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon-sm" className="relative" aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`}>
          <Bell />
          {unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-loss px-1 text-[10px] font-semibold text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-semibold">Notifications</span>
          <div className="flex items-center gap-1">
            <Button size="xs" variant="ghost" disabled={!unread} onClick={() => readAll.mutate()}>
              <CheckCheck className="h-3.5 w-3.5" /> Mark all read
            </Button>
            <Button size="icon-sm" variant="ghost" asChild aria-label="Notification settings" onClick={() => setOpen(false)}>
              <Link href="/profile?tab=notifications">
                <Settings className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </div>
        </div>
        <ul className="max-h-[420px] overflow-y-auto scrollbar-thin">
          {(q.data?.items ?? []).length === 0 && <li className="px-3 py-8 text-center text-xs text-muted-foreground">You&apos;re all caught up.</li>}
          {(q.data?.items ?? []).map((n) => {
            const Icon = ICON[n.kind] ?? Info;
            return (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => !n.read_at && read(n.id)}
                  className={cn("flex w-full gap-2.5 border-b px-3 py-2.5 text-left transition-colors hover:bg-accent/50", !n.read_at && "bg-primary/5")}
                >
                  <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", n.kind === "risk" || n.kind === "error" ? "text-loss" : "text-primary")} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5 text-xs font-medium">
                      {!n.read_at && <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="unread" />}
                      <span className="truncate">{n.title}</span>
                    </span>
                    {n.body ? <span className="line-clamp-2 text-2xs text-muted-foreground">{n.body}</span> : null}
                    <span className="text-[10px] text-muted-foreground">
                      {timeAgo(n.created_at)}
                      {n.channels_sent.length ? ` · sent via ${n.channels_sent.join(", ")}` : ""}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

/** Banner while an account deletion is pending (DPDP grace period). */
export function DeletionBanner() {
  const user = useAuth((s) => s.user);
  if (!user?.deletion_requested_at) return null;
  const purge = new Date(new Date(user.deletion_requested_at).getTime() + 7 * 86_400_000);
  return (
    <div className="flex flex-wrap items-center justify-center gap-2 border-b border-loss/30 bg-loss/10 px-4 py-1.5 text-xs text-loss" role="alert">
      <AlertTriangle className="h-3.5 w-3.5" /> Account deletion scheduled for {purge.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}. Trading is halted.
      <Link href="/profile?tab=privacy" className="font-medium underline">
        Cancel deletion
      </Link>
    </div>
  );
}
