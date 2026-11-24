"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Trash2, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { apiJson } from "@/lib/api";
import { INDICATOR_BY_ID, INDICATORS, type IndicatorDef, indicatorLabel, SOURCES } from "@/lib/chart/indicators";
import { fmtPrice } from "@/lib/chart/series";
import { cn } from "@/lib/utils";
import { shortSymbol } from "./chart-cell";
import { cellApis, indicator, useTerminal } from "./store";

const CATEGORIES = ["Moving averages", "Bands & channels", "Trend", "Momentum", "Volatility", "Volume"] as const;

/** Indicator picker + settings for the active chart. Also opens from a legend's gear icon. */
export function IndicatorsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const activeIdx = useTerminal((s) => s.layout.active);
  const cell = useTerminal((s) => s.layout.cells[s.layout.active]!);
  const setCell = useTerminal((s) => s.setCell);
  const [q, setQ] = React.useState("");
  const [cat, setCat] = React.useState<string>("All");
  const [editing, setEditing] = React.useState<string | null>(null);

  React.useEffect(() => {
    const onEdit = (e: Event) => {
      const d = (e as CustomEvent<{ index: number; uid: string }>).detail;
      useTerminal.getState().setActive(d.index);
      setEditing(d.uid);
      onOpenChange(true);
    };
    window.addEventListener("chart:edit-indicator", onEdit);
    return () => window.removeEventListener("chart:edit-indicator", onEdit);
  }, [onOpenChange]);

  const list = INDICATORS.filter((d) => (cat === "All" || d.category === cat) && (!q || `${d.name} ${d.short} ${d.id}`.toLowerCase().includes(q.toLowerCase())));
  const add = (def: IndicatorDef) => {
    const ind = indicator(def.id);
    setCell(activeIdx, { indicators: [...cell.indicators, ind] });
    setEditing(ind.uid);
    toast.success(`${def.name} added`);
  };
  const edited = cell.indicators.find((i) => i.uid === editing);
  const editedDef = edited ? INDICATOR_BY_ID[edited.id] : undefined;
  const setParam = (key: string, value: number | string) =>
    setCell(activeIdx, { indicators: cell.indicators.map((i) => (i.uid === editing ? { ...i, params: { ...i.params, [key]: value } } : i)) });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl p-0">
        <DialogHeader className="border-b px-4 pb-3 pt-4">
          <DialogTitle>Indicators</DialogTitle>
          <DialogDescription>
            {INDICATORS.length} studies for {shortSymbol(cell.symbol)}. Click to add; values update live with every tick.
          </DialogDescription>
        </DialogHeader>
        <div className="grid min-h-[420px] grid-cols-1 sm:grid-cols-[1fr_260px]">
          <div className="flex min-h-0 flex-col border-r">
            <div className="flex flex-wrap items-center gap-1.5 border-b p-2">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
                <Input autoFocus className="h-8 pl-8 text-xs" placeholder="Search indicators" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search indicators" />
              </div>
              {["All", ...CATEGORIES].map((c) => (
                <button key={c} onClick={() => setCat(c)} className={cn("rounded-full px-2 py-0.5 text-[11px]", cat === c ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}>
                  {c}
                </button>
              ))}
            </div>
            <div className="max-h-[380px] overflow-y-auto p-1">
              {list.map((d) => (
                <button key={d.id} onClick={() => add(d)} className="flex w-full items-start gap-3 rounded-md px-2 py-1.5 text-left hover:bg-muted">
                  <span className="mt-0.5 w-16 shrink-0 rounded bg-muted px-1 text-center text-[10px] font-medium text-muted-foreground">{d.short}</span>
                  <span className="min-w-0">
                    <span className="block text-xs font-medium">{d.name}</span>
                    <span className="block truncate text-[11px] text-muted-foreground">{d.description}</span>
                  </span>
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">{d.overlay ? "on price" : "pane"}</span>
                </button>
              ))}
              {list.length === 0 && <p className="p-4 text-center text-xs text-muted-foreground">No indicator matches “{q}”.</p>}
            </div>
          </div>
          <div className="flex min-h-0 flex-col">
            <p className="border-b px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">On this chart</p>
            <div className="max-h-[200px] overflow-y-auto p-1">
              {cell.indicators.length === 0 && <p className="p-3 text-xs text-muted-foreground">None yet.</p>}
              {cell.indicators.map((i) => {
                const d = INDICATOR_BY_ID[i.id];
                if (!d) return null;
                return (
                  <div key={i.uid} className={cn("flex items-center gap-1 rounded px-2 py-1 text-xs", editing === i.uid && "bg-muted")}>
                    <button className="flex-1 truncate text-left" onClick={() => setEditing(i.uid)}>
                      {indicatorLabel(d, i.params)}
                    </button>
                    <button aria-label={`Remove ${d.short}`} className="rounded p-0.5 text-muted-foreground hover:text-loss" onClick={() => setCell(activeIdx, { indicators: cell.indicators.filter((x) => x.uid !== i.uid) })}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
            {edited && editedDef && (
              <div className="border-t p-3 text-xs">
                <p className="mb-2 font-medium">{editedDef.name}</p>
                {editedDef.params.length === 0 && <p className="text-muted-foreground">No parameters.</p>}
                <div className="flex flex-col gap-2">
                  {editedDef.params.map((p) => (
                    <label key={p.key} className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{p.label}</span>
                      {p.type === "source" ? (
                        <select className="h-7 w-28 rounded border bg-background px-1" value={String(edited.params[p.key] ?? p.default)} onChange={(e) => setParam(p.key, e.target.value)}>
                          {SOURCES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="number"
                          className="h-7 w-28 rounded border bg-background px-2 text-right"
                          min={p.min}
                          max={p.max}
                          step={p.step ?? (p.type === "int" ? 1 : 0.1)}
                          value={Number(edited.params[p.key] ?? p.default)}
                          onChange={(e) => {
                            const v = Number(e.target.value);
                            if (!Number.isFinite(v)) return;
                            const clamped = Math.min(p.max ?? Infinity, Math.max(p.min ?? -Infinity, p.type === "int" ? Math.round(v) : v));
                            setParam(p.key, clamped);
                          }}
                        />
                      )}
                    </label>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">{editedDef.description}</p>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Create a price alert for the active chart's symbol. */
export function AlertDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const active = useTerminal((s) => s.layout.active);
  const symbol = useTerminal((s) => s.layout.cells[s.layout.active]!.symbol);
  const [price, setPrice] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [email, setEmail] = React.useState(false);
  const qc = useQueryClient();
  React.useEffect(() => {
    if (open) {
      const last = cellApis.get(active)?.lastPrice();
      setPrice(last ? last.toFixed(2) : "");
      setMessage("");
    }
  }, [open, active]);
  const m = useMutation({
    mutationFn: () => apiJson<{ op: string; value: number }>("/api/alerts", { method: "POST", body: JSON.stringify({ symbol, value: Number(price), message, channels: email ? ["in_app", "email"] : ["in_app"] }) }),
    onSuccess: (a) => {
      toast.success(`Alert set: ${shortSymbol(symbol)} ${a.op === "above" ? "crosses above" : "falls below"} ${fmtPrice(a.value)}`);
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const last = cellApis.get(active)?.lastPrice() ?? null;
  const p = Number(price);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Price alert · {shortSymbol(symbol)}</DialogTitle>
          <DialogDescription>
            Fires once when the last traded price reaches the level{last ? ` (now ${fmtPrice(last)})` : ""}. You get an in-app notification
            {email ? " and an email" : ""}.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            m.mutate();
          }}
        >
          <label className="flex flex-col gap-1 text-xs">
            Price
            <Input type="number" step="any" min="0" value={price} onChange={(e) => setPrice(e.target.value)} autoFocus aria-label="Alert price" />
            {last != null && p > 0 && <span className="text-muted-foreground">{p >= last ? "Triggers when the price rises to this level" : "Triggers when the price falls to this level"}</span>}
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Message (optional)
            <Input value={message} maxLength={300} onChange={(e) => setMessage(e.target.value)} placeholder="e.g. breakout above resistance" />
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> Also email me
          </label>
          <Button type="submit" loading={m.isPending} disabled={!(p > 0)}>
            Create alert
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const COLOR_PRESETS: { name: string; up: string; down: string }[] = [
  { name: "Green / red", up: "#089981", down: "#f23645" },
  { name: "Blue / orange (colour-blind safe)", up: "#2962ff", down: "#ff9800" },
  { name: "Teal / pink", up: "#26a69a", down: "#ef5350" },
  { name: "Monochrome", up: "#b2b5be", down: "#5d606b" },
];

export function SettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const settings = useTerminal((s) => s.layout.settings);
  const setLayout = useTerminal((s) => s.setLayout);
  const set = (patch: Partial<typeof settings>) => setLayout((l) => ({ ...l, settings: { ...l.settings, ...patch } }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Chart settings</DialogTitle>
          <DialogDescription>Applies to every chart in this layout. Times are shown in IST.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-xs">
          <div>
            <p className="mb-1.5 font-medium">Candle colours</p>
            <div className="flex flex-col gap-1">
              {COLOR_PRESETS.map((c) => (
                <button key={c.name} onClick={() => set({ upColor: c.up, downColor: c.down })} className={cn("flex items-center gap-2 rounded border px-2 py-1.5 text-left", settings.upColor === c.up && settings.downColor === c.down ? "border-primary" : "hover:bg-muted")}>
                  <span className="h-3 w-3 rounded-sm" style={{ background: c.up }} />
                  <span className="h-3 w-3 rounded-sm" style={{ background: c.down }} />
                  {c.name}
                </button>
              ))}
            </div>
          </div>
          {(
            [
              ["grid", "Grid lines"],
              ["watermark", "Symbol watermark"],
              ["magnet", "Magnet: snap drawings and crosshair to OHLC"],
            ] as const
          ).map(([k, label]) => (
            <label key={k} className="flex items-center justify-between gap-2">
              {label}
              <input type="checkbox" checked={settings[k]} onChange={(e) => set({ [k]: e.target.checked })} />
            </label>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export interface LayoutRow {
  id: number;
  name: string;
  is_default: boolean;
  updated_at: string | null;
}

export function RenameDialog({ open, onOpenChange, initial, title, onSubmit }: { open: boolean; onOpenChange: (o: boolean) => void; initial: string; title: string; onSubmit: (name: string) => void }) {
  const [name, setName] = React.useState(initial);
  React.useEffect(() => setName(initial), [initial, open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) onSubmit(name.trim());
          }}
        >
          <Input autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)} aria-label="Layout name" />
          <Button type="submit">Save</Button>
          <Button type="button" variant="ghost" size="icon" aria-label="Cancel" onClick={() => onOpenChange(false)}>
            <X />
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
