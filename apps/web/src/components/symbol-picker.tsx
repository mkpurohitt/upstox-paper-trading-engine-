"use client";
import { Search, X } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/misc";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Hit {
  symbol: string;
  name: string;
  instrument_type: string;
}

export function SymbolSearch({
  onPick,
  placeholder = "Search symbol…",
  filter,
  className,
  autoFocus,
}: {
  onPick: (symbol: string) => void;
  placeholder?: string;
  filter?: (h: Hit) => boolean;
  className?: string;
  autoFocus?: boolean;
}) {
  const [q, setQ] = React.useState("");
  const [hits, setHits] = React.useState<Hit[]>([]);
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(0);
  React.useEffect(() => {
    if (q.trim().length < 1) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      apiJson<Hit[]>(`/api/market/search?q=${encodeURIComponent(q)}&limit=12`)
        .then((h) => {
          setHits(filter ? h.filter(filter) : h);
          setActive(0);
          setOpen(true);
        })
        .catch(() => setHits([]));
    }, 120);
    return () => clearTimeout(t);
  }, [q, filter]);
  const pick = (s: string) => {
    onPick(s);
    setQ("");
    setOpen(false);
  };
  return (
    <Popover open={open && hits.length > 0} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className={cn("relative", className)}>
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            autoFocus={autoFocus}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setActive((a) => Math.min(hits.length - 1, a + 1));
              else if (e.key === "ArrowUp") setActive((a) => Math.max(0, a - 1));
              else if (e.key === "Enter" && hits[active]) {
                e.preventDefault();
                pick(hits[active]!.symbol);
              }
            }}
            placeholder={placeholder}
            aria-label={placeholder}
            className="flex h-9 w-full rounded-md border border-input bg-transparent py-1 pl-8 pr-3 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-1" onOpenAutoFocus={(e) => e.preventDefault()}>
        <ul role="listbox">
          {hits.map((h, i) => (
            <li key={h.symbol}>
              <button
                type="button"
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(h.symbol)}
                className={cn("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm", i === active ? "bg-accent" : "hover:bg-accent/60")}
              >
                <span className="font-medium">{h.symbol}</span>
                <span className="truncate text-xs text-muted-foreground">{h.name}</span>
                <Badge variant="secondary" className="ml-auto">
                  {h.instrument_type}
                </Badge>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

export function SymbolMultiPicker({ value, onChange, max = 20 }: { value: string[]; onChange: (v: string[]) => void; max?: number }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1">
        {value.map((s) => (
          <Badge key={s} variant="secondary" className="gap-1 py-1 text-xs">
            {s}
            <button type="button" aria-label={`Remove ${s}`} onClick={() => onChange(value.filter((x) => x !== s))}>
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
        {!value.length && <span className="text-xs text-muted-foreground">No symbols yet</span>}
      </div>
      {value.length < max && <SymbolSearch onPick={(s) => !value.includes(s) && onChange([...value, s])} placeholder="Add symbol (e.g. RELIANCE, NIFTY)" />}
    </div>
  );
}
