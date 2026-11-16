"use client";
import { AlertTriangle, Info, type LucideIcon } from "lucide-react";
import * as React from "react";
import { inr, num, pct } from "@/lib/format";
import { cn, pnlClass } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  icon: Icon,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-3 pb-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight sm:text-xl">
          {Icon ? <Icon className="h-5 w-5 text-primary" aria-hidden /> : null}
          {title}
        </h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({
  icon: Icon = Info,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center", className)}>
      <div className="rounded-full bg-muted p-3">
        <Icon className="h-5 w-5 text-muted-foreground" aria-hidden />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {description ? <p className="max-w-sm text-xs text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "profit" | "loss" | "warning" | "default";
  className?: string;
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-3", className)}>
      <div className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={cn(
          "num mt-1 text-lg font-semibold",
          tone === "profit" && "text-profit",
          tone === "loss" && "text-loss",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-2xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

/** Coloured P&L number. Includes a +/- sign and arrow for colour-blind users. */
export function Pnl({
  value,
  kind = "inr",
  digits = 2,
  className,
  arrow = false,
}: {
  value: number | null | undefined;
  kind?: "inr" | "pct" | "num";
  digits?: number;
  className?: string;
  arrow?: boolean;
}) {
  const v = value ?? 0;
  const text = kind === "inr" ? inr(value, { signed: true }) : kind === "pct" ? pct(value, digits) : (v > 0 ? "+" : "") + num(value, digits);
  return (
    <span className={cn("num", pnlClass(value), className)}>
      {arrow && value ? (v > 0 ? "▲ " : "▼ ") : null}
      {text}
    </span>
  );
}

export function Disclaimer({ kind = "trading", className }: { kind?: "trading" | "ai" | "options"; className?: string }) {
  const text = {
    trading:
      "Trading in equities and derivatives involves substantial risk of loss. Past or simulated performance is not indicative of future results. Paper trading and backtests do not account for all real-world frictions.",
    ai: "AI responses are for education and analysis only and are not investment advice or a recommendation to buy or sell any security. Verify all figures independently.",
    options:
      "Options are leveraged instruments; you can lose more than your premium on short positions. Theoretical values use Black-Scholes and may differ from market prices.",
  }[kind];
  return (
    <p className={cn("flex items-start gap-1.5 text-2xs leading-relaxed text-muted-foreground", className)}>
      <AlertTriangle className="mt-px h-3 w-3 shrink-0 text-warning" aria-hidden />
      <span>{text}</span>
    </p>
  );
}

export function SectionTitle({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{children}</h2>
      {actions}
    </div>
  );
}

export function LiveDot({ status }: { status: "open" | "connecting" | "closed" | "idle" }) {
  const color = status === "open" ? "bg-profit" : status === "connecting" ? "bg-warning" : "bg-muted-foreground";
  return (
    <span className="relative flex h-2 w-2" aria-label={`realtime ${status}`}>
      {status === "open" && <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", color)} />}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", color)} />
    </span>
  );
}
