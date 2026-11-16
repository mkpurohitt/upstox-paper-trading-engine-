"use client";
import { Command } from "cmdk";
import { Contrast, LogOut, Moon, Plus, Search, ShieldAlert, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/misc";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { usePrefs } from "@/lib/prefs";
import { NAV } from "./nav";

interface SymbolHit {
  symbol: string;
  name: string;
  instrument_type: string;
}

const ANALYSIS = [
  ["option-chain", "Option Chain"],
  ["arbitrage", "Arbitrage Scanner"],
  ["ratio-spreads", "Ratio Spread Scanner"],
  ["straddle", "Straddle / Strangle"],
  ["fly-condor", "Butterfly / Iron Condor"],
  ["options-builder", "Options Strategy Builder"],
  ["technical", "Technical Dashboard"],
  ["fundamental", "Fundamental Dashboard"],
  ["quant", "Quant Dashboard"],
  ["pairs", "Pair Trading"],
  ["screener", "Screener"],
  ["market-overview", "Market Overview"],
] as const;

export function CommandPalette({ open, onOpenChange, onKillSwitch }: { open: boolean; onOpenChange: (o: boolean) => void; onKillSwitch: () => void }) {
  const router = useRouter();
  const { setTheme, resolvedTheme } = useTheme();
  const { colourBlind, setColourBlind } = usePrefs();
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<SymbolHit[]>([]);

  React.useEffect(() => {
    if (query.trim().length < 2) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      apiJson<SymbolHit[]>(`/api/market/search?q=${encodeURIComponent(query)}&limit=8`)
        .then(setHits)
        .catch(() => setHits([]));
    }, 150);
    return () => clearTimeout(t);
  }, [query]);

  const go = (href: string) => {
    onOpenChange(false);
    setQuery("");
    router.push(href);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0" aria-describedby={undefined}>
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command shouldFilter={hits.length === 0} className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:text-muted-foreground">
          <div className="flex items-center gap-2 border-b px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Search symbols, pages, actions…"
              className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <Kbd>Esc</Kbd>
          </div>
          <Command.List className="max-h-[60vh] overflow-y-auto p-1.5 scrollbar-thin">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">No results.</Command.Empty>
            {hits.length > 0 && (
              <Command.Group heading="Symbols">
                {hits.map((h) => (
                  <Item key={h.symbol} onSelect={() => go(`/analysis/technical?symbol=${encodeURIComponent(h.symbol)}`)} value={`${h.symbol} ${h.name}`}>
                    <span className="font-medium">{h.symbol}</span>
                    <span className="truncate text-muted-foreground">{h.name}</span>
                    <span className="ml-auto text-2xs text-muted-foreground">{h.instrument_type}</span>
                  </Item>
                ))}
              </Command.Group>
            )}
            <Command.Group heading="Navigate">
              {NAV.filter((n) => !n.admin || user?.role === "admin").map((n) => (
                <Item key={n.href} onSelect={() => go(n.href)} value={`${n.label} ${n.description}`}>
                  <n.icon className="h-4 w-4" />
                  {n.label}
                  <span className="text-muted-foreground">— {n.description}</span>
                  <Kbd className="ml-auto">{n.shortcut}</Kbd>
                </Item>
              ))}
            </Command.Group>
            <Command.Group heading="Analysis">
              {ANALYSIS.map(([slug, label]) => (
                <Item key={slug} onSelect={() => go(`/analysis/${slug}`)} value={`analysis ${label}`}>
                  {label}
                </Item>
              ))}
            </Command.Group>
            <Command.Group heading="Actions">
              <Item onSelect={() => go("/build/new")} value="new strategy create">
                <Plus className="h-4 w-4" /> New strategy
              </Item>
              <Item onSelect={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")} value="toggle theme dark light">
                {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />} Toggle theme
              </Item>
              <Item onSelect={() => setColourBlind(!colourBlind)} value="colour blind palette accessibility">
                <Contrast className="h-4 w-4" /> {colourBlind ? "Disable" : "Enable"} colour-blind P&L palette
              </Item>
              <Item
                onSelect={() => {
                  onOpenChange(false);
                  onKillSwitch();
                }}
                value="kill switch emergency stop"
              >
                <ShieldAlert className="h-4 w-4 text-loss" /> Kill switch…
              </Item>
              <Item
                onSelect={async () => {
                  onOpenChange(false);
                  await logout();
                  router.push("/login");
                }}
                value="sign out logout"
              >
                <LogOut className="h-4 w-4" /> Sign out
              </Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function Item({ children, onSelect, value }: { children: React.ReactNode; onSelect: () => void; value: string }) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm aria-selected:bg-accent"
    >
      {children}
    </Command.Item>
  );
}
