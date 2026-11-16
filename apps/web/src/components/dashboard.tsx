"use client";
import { ArrowLeft, Download, RefreshCw, Sparkles, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { downloadCsv } from "@/lib/csv";
import { usePrefs } from "@/lib/prefs";
import { cn } from "@/lib/utils";

/** Send a dashboard's context to the copilot and open it. */
export function useAskAI() {
  const router = useRouter();
  const setCtx = usePrefs((s) => s.setCopilotContext);
  return React.useCallback(
    (question: string, context: unknown) => {
      const ctx = typeof context === "string" ? context : JSON.stringify(context).slice(0, 6000);
      setCtx(ctx);
      router.push(`/?q=${encodeURIComponent(question)}`);
    },
    [router, setCtx],
  );
}

export function DashboardHeader({
  title,
  description,
  icon: Icon,
  filters,
  csv,
  ask,
  onRefresh,
  refreshing,
  className,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  filters?: React.ReactNode;
  csv?: { filename: string; rows: () => Record<string, unknown>[] };
  ask?: { question: string; context: () => unknown };
  onRefresh?: () => void;
  refreshing?: boolean;
  className?: string;
}) {
  const askAI = useAskAI();
  return (
    <div className={cn("mb-4 flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="ghost" size="icon-sm" asChild aria-label="Back to analysis">
            <Link href="/analysis">
              <ArrowLeft />
            </Link>
          </Button>
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              {Icon ? <Icon className="h-5 w-5 text-primary" aria-hidden /> : null}
              {title}
            </h1>
            {description ? <p className="truncate text-xs text-muted-foreground">{description}</p> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {onRefresh ? (
            <Tooltip content="Refresh">
              <Button variant="outline" size="icon-sm" onClick={onRefresh} aria-label="Refresh">
                <RefreshCw className={cn(refreshing && "animate-spin")} />
              </Button>
            </Tooltip>
          ) : null}
          {csv ? (
            <Button variant="outline" size="sm" onClick={() => downloadCsv(csv.filename, csv.rows())}>
              <Download /> CSV
            </Button>
          ) : null}
          {ask ? (
            <Button size="sm" onClick={() => askAI(ask.question, ask.context())}>
              <Sparkles /> Ask AI about this
            </Button>
          ) : null}
        </div>
      </div>
      {filters ? <div className="flex flex-wrap items-end gap-2 rounded-lg border bg-card p-2">{filters}</div> : null}
    </div>
  );
}

export function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("flex min-w-[120px] flex-col gap-1", className)}>
      <span className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
