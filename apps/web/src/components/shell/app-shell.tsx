"use client";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ChevronsLeft, ChevronsRight, LogOut, Moon, Search, Sun, UserRound } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import { LiveDot } from "@/components/common";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, Kbd, Skeleton } from "@/components/ui/misc";
import { Tooltip } from "@/components/ui/tooltip";
import { useTicks } from "@/hooks/use-realtime";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { num, pct } from "@/lib/format";
import { usePrefs } from "@/lib/prefs";
import { cn, pnlClass } from "@/lib/utils";
import { realtime, useWsStatus } from "@/lib/ws";
import { ApiStatusBanner } from "./api-status";
import { CommandPalette } from "./command-palette";
import { KillSwitchButton, KillSwitchDialog } from "./kill-switch";
import { NAV } from "./nav";
import { DeletionBanner, NotificationsBell } from "./notifications";

const INDEX_STRIP = ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "BSE_INDEX:SENSEX", "NSE_INDEX:INDIAVIX"];
const LABEL: Record<string, string> = {
  "NSE_INDEX:NIFTY": "NIFTY 50",
  "NSE_INDEX:BANKNIFTY": "BANK NIFTY",
  "BSE_INDEX:SENSEX": "SENSEX",
  "NSE_INDEX:INDIAVIX": "INDIA VIX",
};

interface QuoteLite {
  symbol: string;
  ltp: number;
  change_pct?: number | null;
}

function IndexStrip() {
  const { data } = useQuery({
    queryKey: ["quotes", INDEX_STRIP],
    queryFn: () => apiJson<QuoteLite[]>(`/api/market/quotes?symbols=${INDEX_STRIP.join(",")}`),
    staleTime: 60_000,
  });
  const live = useTicks(INDEX_STRIP);
  if (!data) {
    return (
      <div className="hidden gap-4 md:flex">
        {INDEX_STRIP.map((s) => (
          <Skeleton key={s} className="h-4 w-24" />
        ))}
      </div>
    );
  }
  return (
    <div className="hidden min-w-0 items-center gap-4 overflow-hidden md:flex" aria-label="Index prices">
      {data.map((q) => {
        const t = live[q.symbol];
        const ltp = t?.ltp ?? q.ltp;
        const ch = t?.change_pct ?? q.change_pct ?? 0;
        return (
          <Link key={q.symbol} href={`/analysis/technical?symbol=${encodeURIComponent(q.symbol)}`} className="flex items-baseline gap-1.5 whitespace-nowrap text-xs">
            <span className="text-muted-foreground">{LABEL[q.symbol] ?? q.symbol}</span>
            <span className="num font-medium">{num(ltp)}</span>
            <span className={cn("num text-2xs", pnlClass(ch))}>{pct(ch)}</span>
          </Link>
        );
      })}
    </div>
  );
}

function MarketStatus() {
  const { data } = useQuery({
    queryKey: ["market-status"],
    queryFn: () => apiJson<{ is_open: boolean; status: string }[]>("/api/market/status"),
    refetchInterval: 60_000,
  });
  const nse = data?.[0];
  if (!nse) return null;
  return (
    <span className={cn("hidden whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-medium sm:inline-flex", nse.is_open ? "bg-profit/15 text-profit" : "bg-muted text-muted-foreground")}>
      {nse.is_open ? "Market open" : "Market closed"}
    </span>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const user = useAuth((s) => s.user);
  const { sidebarCollapsed, toggleSidebar } = usePrefs();
  const items = NAV.filter((n) => !n.admin || user?.role === "admin");
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r bg-surface transition-[width] duration-200 md:flex",
        sidebarCollapsed ? "w-[60px]" : "w-[216px]",
      )}
    >
      <div className="flex h-14 items-center gap-2 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-primary to-info text-xs font-bold text-white">A</div>
        {!sidebarCollapsed && <span className="text-sm font-semibold tracking-tight">AlgoDesk</span>}
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 px-2 py-2" aria-label="Main">
        {items.map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
          const link = (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                active && "bg-accent text-foreground",
              )}
            >
              {active && <motion.span layoutId="nav-active" className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary" />}
              <n.icon className="h-4 w-4 shrink-0" aria-hidden />
              {!sidebarCollapsed && <span>{n.label}</span>}
            </Link>
          );
          return sidebarCollapsed ? (
            <Tooltip key={n.href} side="right" content={n.label}>
              {link}
            </Tooltip>
          ) : (
            link
          );
        })}
      </nav>
      <div className="border-t p-2">
        <Button variant="ghost" size="sm" className="w-full justify-start gap-3 text-muted-foreground" onClick={toggleSidebar} aria-label="Toggle sidebar">
          {sidebarCollapsed ? <ChevronsRight /> : <ChevronsLeft />}
          {!sidebarCollapsed && "Collapse"}
        </Button>
      </div>
    </aside>
  );
}

function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex h-14 items-stretch border-t bg-surface/95 backdrop-blur md:hidden" aria-label="Mobile">
      {NAV.filter((n) => n.mobile).map((n) => {
        const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
        return (
          <Link key={n.href} href={n.href} className={cn("flex flex-1 flex-col items-center justify-center gap-0.5 text-2xs", active ? "text-primary" : "text-muted-foreground")}>
            <n.icon className="h-4 w-4" aria-hidden />
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

function UserMenu() {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const router = useRouter();
  if (!user) return <Skeleton className="h-8 w-8 rounded-full" />;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="rounded-full" aria-label="Account menu">
        <Avatar name={user.full_name || user.email} src={user.avatar_url} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <div className="truncate text-sm font-medium text-foreground">{user.full_name || "Trader"}</div>
          <div className="truncate">{user.email}</div>
          <div className="mt-1 text-2xs uppercase text-primary">{user.plan} plan</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/profile")}>
          <UserRound /> Profile & settings
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={async () => {
            await logout();
            router.push("/login");
          }}
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function useGlobalShortcuts(openPalette: () => void) {
  const router = useRouter();
  React.useEffect(() => {
    let leader = 0;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openPalette();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        openPalette();
        return;
      }
      if (e.key === "g") {
        leader = Date.now();
        return;
      }
      if (Date.now() - leader < 1000) {
        const hit = NAV.find((n) => n.shortcut.split(" ")[1]?.toLowerCase() === e.key.toLowerCase());
        if (hit) router.push(hit.href);
        leader = 0;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openPalette, router]);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const status = useAuth((s) => s.status);
  const bootstrap = useAuth((s) => s.bootstrap);
  const router = useRouter();
  const pathname = usePathname();
  const wsStatus = useWsStatus((s) => s.status);
  const { theme, setTheme, resolvedTheme } = useTheme();
  const colourBlind = usePrefs((s) => s.colourBlind);
  const [palette, setPalette] = React.useState(false);
  const [kill, setKill] = React.useState(false);
  const openPalette = React.useCallback(() => setPalette(true), []);
  useGlobalShortcuts(openPalette);

  React.useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  React.useEffect(() => {
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [status, router, pathname]);

  React.useEffect(() => {
    if (status !== "authenticated") return;
    const rt = realtime(() => useAuth.getState().token);
    rt.start();
    return () => rt.stop();
  }, [status]);

  React.useEffect(() => {
    document.documentElement.dataset.cb = colourBlind ? "true" : "false";
  }, [colourBlind]);

  if (status !== "authenticated") {
    return (
      <div className="flex h-dvh items-center justify-center" role="status" aria-live="polite">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-xs text-muted-foreground">Loading your workspace…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-1.5 focus:text-primary-foreground">
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <ApiStatusBanner />
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/85 px-3 backdrop-blur sm:px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-primary to-info text-xs font-bold text-white md:hidden">A</div>
          <button
            onClick={openPalette}
            className="flex h-8 w-full max-w-[260px] items-center gap-2 rounded-md border bg-muted/40 px-2.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
            aria-label="Open command palette"
          >
            <Search className="h-3.5 w-3.5" />
            <span className="flex-1 text-left">Search or jump to…</span>
            <Kbd className="hidden sm:inline-flex">⌘K</Kbd>
          </button>
          <IndexStrip />
          <div className="ml-auto flex items-center gap-1.5">
            <MarketStatus />
            <Tooltip content={`Realtime: ${wsStatus}`}>
              <span className="hidden p-2 sm:inline-flex">
                <LiveDot status={wsStatus} />
              </span>
            </Tooltip>
            <KillSwitchButton onClick={() => setKill(true)} />
            <NotificationsBell />
            <Tooltip content="Toggle theme">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Toggle theme"
                onClick={() => setTheme((resolvedTheme ?? theme) === "dark" ? "light" : "dark")}
              >
                {resolvedTheme === "dark" ? <Sun /> : <Moon />}
              </Button>
            </Tooltip>
            <UserMenu />
          </div>
        </header>
        <DeletionBanner />
        <main id="main" className="flex-1 px-3 pb-20 pt-4 sm:px-6 md:pb-8">
          {children}
        </main>
      </div>
      <MobileNav />
      <CommandPalette open={palette} onOpenChange={setPalette} onKillSwitch={() => setKill(true)} />
      <KillSwitchDialog open={kill} onOpenChange={setKill} />
    </div>
  );
}
