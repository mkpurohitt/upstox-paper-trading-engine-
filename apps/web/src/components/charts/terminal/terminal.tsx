"use client";
/**
 * The Charts terminal: toolbars, multi-chart grid, side panels, layouts (auto-saved), keyboard shortcuts.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  ArrowUpRight,
  Bell,
  Camera,
  CandlestickChart,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  Info,
  LayoutGrid,
  List,
  Lock,
  Magnet,
  Maximize2,
  Minimize2,
  Minus,
  MousePointer2,
  MoveDiagonal,
  MoveHorizontal,
  Plus,
  Redo2,
  Rewind,
  Ruler,
  Search,
  Settings2,
  Shapes,
  Slash,
  Square,
  Trash2,
  Type,
  Undo2,
  Unlock,
  X,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { SymbolSearch } from "@/components/symbol-picker";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/misc";
import { Tooltip } from "@/components/ui/tooltip";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { type DrawingType, TOOL_LABEL } from "@/lib/chart/drawings";
import { TIMEFRAMES, tfLabel } from "@/lib/chart/series";
import { cn } from "@/lib/utils";
import { type BarsResp, ChartCell, shortSymbol } from "./chart-cell";
import { AlertDialog, IndicatorsDialog, type LayoutRow, RenameDialog, SettingsDialog } from "./dialogs";
import { AlertsPanel, DetailsPanel, ObjectsPanel, WatchlistPanel } from "./side-panels";
import { cellApis, CHART_TYPES, defaultLayout, GRID_CELLS, type GridKind, type LayoutState, NO_DRAWINGS, RANGES, type Tool, useTerminal } from "./store";

const QUICK_TF = ["1", "5", "15", "60", "D"];

const TOOLS: { id: Tool; icon: React.ComponentType<{ className?: string }>; key?: string }[] = [
  { id: "cursor", icon: MousePointer2, key: "Esc" },
  { id: "trend", icon: Slash, key: "Alt+T" },
  { id: "ray", icon: ArrowUpRight },
  { id: "extended", icon: MoveDiagonal },
  { id: "hline", icon: Minus, key: "Alt+H" },
  { id: "hray", icon: MoveHorizontal },
  { id: "vline", icon: Minus, key: "Alt+V" },
  { id: "rect", icon: Square, key: "Alt+R" },
  { id: "channel", icon: Shapes, key: "Alt+C" },
  { id: "fib", icon: LayoutGrid, key: "Alt+F" },
  { id: "measure", icon: Ruler, key: "Alt+M" },
  { id: "long", icon: ArrowUpCircle },
  { id: "short", icon: ArrowDownCircle },
  { id: "text", icon: Type },
];

const SHORTCUTS: Record<string, Tool> = { KeyT: "trend", KeyH: "hline", KeyV: "vline", KeyR: "rect", KeyC: "channel", KeyF: "fib", KeyM: "measure" };

function useSource(symbol: string, tf: string) {
  // the first page of the active chart carries the data-source label (shared cache with the chart itself)
  const qc = useQueryClient();
  const data = qc.getQueryData<{ pages: BarsResp[] }>(["chart-bars", symbol, tf]);
  const q = useQuery({ queryKey: ["chart-source"], queryFn: () => apiJson<BarsResp["source"]>("/api/charts/source"), refetchInterval: 60_000 });
  return data?.pages[0]?.source ?? q.data;
}

function Clock() {
  const [now, setNow] = React.useState<string>("");
  React.useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }));
    tick();
    const h = setInterval(tick, 1000);
    return () => clearInterval(h);
  }, []);
  return <span className="num">{now} IST</span>;
}

function DrawingToolbar() {
  const tool = useTerminal((s) => s.tool);
  const magnet = useTerminal((s) => s.layout.settings.magnet);
  const symbol = useTerminal((s) => s.layout.cells[s.layout.active]!.symbol);
  const drawings = useTerminal((s) => s.layout.drawings[symbol] ?? NO_DRAWINGS);
  const { setTool, setLayout, setDrawings } = useTerminal.getState();
  const allLocked = drawings.length > 0 && drawings.every((d) => d.locked);
  const allHidden = drawings.length > 0 && drawings.every((d) => d.hidden);
  const btn = "flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";
  return (
    <div className="hidden w-10 shrink-0 flex-col items-center gap-0.5 overflow-y-auto border-r bg-card py-1 md:flex" role="toolbar" aria-label="Drawing tools" aria-orientation="vertical">
      {TOOLS.map((t) => (
        <Tooltip key={t.id} side="right" content={`${t.id === "cursor" ? "Cursor" : TOOL_LABEL[t.id as DrawingType]}${t.key ? ` (${t.key})` : ""}`}>
          <button aria-label={t.id === "cursor" ? "Cursor" : TOOL_LABEL[t.id as DrawingType]} aria-pressed={tool === t.id} className={cn(btn, tool === t.id && "bg-primary/15 text-primary")} onClick={() => setTool(t.id)}>
            <t.icon className={cn("h-4 w-4", t.id === "vline" && "rotate-90")} />
          </button>
        </Tooltip>
      ))}
      <span className="my-1 h-px w-6 bg-border" />
      <Tooltip side="right" content="Magnet: snap to open/high/low/close">
        <button aria-label="Magnet" aria-pressed={magnet} className={cn(btn, magnet && "bg-primary/15 text-primary")} onClick={() => setLayout((l) => ({ ...l, settings: { ...l.settings, magnet: !l.settings.magnet } }))}>
          <Magnet className="h-4 w-4" />
        </button>
      </Tooltip>
      <Tooltip side="right" content={allLocked ? "Unlock all drawings" : "Lock all drawings"}>
        <button aria-label="Lock all drawings" className={btn} disabled={!drawings.length} onClick={() => setDrawings(symbol, drawings.map((d) => ({ ...d, locked: !allLocked })))}>
          {allLocked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
        </button>
      </Tooltip>
      <Tooltip side="right" content={allHidden ? "Show all drawings" : "Hide all drawings"}>
        <button aria-label="Hide all drawings" className={btn} disabled={!drawings.length} onClick={() => setDrawings(symbol, drawings.map((d) => ({ ...d, hidden: !allHidden })))}>
          {allHidden ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
        </button>
      </Tooltip>
      <Tooltip side="right" content="Remove all drawings on this symbol">
        <button
          aria-label="Remove all drawings"
          className={cn(btn, "hover:text-loss")}
          disabled={!drawings.length}
          onClick={() => {
            if (confirm(`Remove all ${drawings.length} drawing(s) on ${shortSymbol(symbol)}? (Ctrl+Z undoes)`)) setDrawings(symbol, []);
          }}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </Tooltip>
    </div>
  );
}

function TopToolbar({ rootRef, onIndicators, onAlert, onSettings, layouts, onLayoutAction }: {
  rootRef: React.RefObject<HTMLDivElement | null>;
  onIndicators: () => void;
  onAlert: () => void;
  onSettings: () => void;
  layouts: LayoutRow[];
  onLayoutAction: (a: { kind: "switch"; id: number } | { kind: "rename" | "saveas" | "default" | "delete" | "new" }) => void;
}) {
  const active = useTerminal((s) => s.layout.active);
  const cell = useTerminal((s) => s.layout.cells[s.layout.active]!);
  const grid = useTerminal((s) => s.layout.grid);
  const sync = useTerminal((s) => s.layout.sync);
  const layoutName = useTerminal((s) => s.layoutName);
  const layoutId = useTerminal((s) => s.layoutId);
  const saveState = useTerminal((s) => s.saveState);
  const canUndo = useTerminal((s) => s.history.past.length > 0);
  const canRedo = useTerminal((s) => s.history.future.length > 0);
  const { setCell, setGrid, setLayout, undo, redo } = useTerminal.getState();
  const source = useSource(cell.symbol, cell.tf);
  const isAdmin = useAuth((s) => s.user?.role === "admin");
  const [symOpen, setSymOpen] = React.useState(false);
  const [cmpOpen, setCmpOpen] = React.useState(false);
  const [custom, setCustom] = React.useState("");
  const [fs, setFs] = React.useState(false);
  React.useEffect(() => {
    const on = () => setFs(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  React.useEffect(() => {
    const open = () => setSymOpen(true);
    window.addEventListener("chart:symbol-search", open);
    return () => window.removeEventListener("chart:symbol-search", open);
  }, []);

  const screenshot = () => {
    const canvas = cellApis.get(active)?.screenshot();
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${shortSymbol(cell.symbol)}_${tfLabel(cell.tf)}_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
  };
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void rootRef.current?.requestFullscreen?.();
  };
  const ib = "h-8 gap-1 px-2 text-xs";
  return (
    <div className="flex h-10 shrink-0 items-center gap-0.5 overflow-x-auto border-b bg-card px-1.5" role="toolbar" aria-label="Chart toolbar">
      <Popover open={symOpen} onOpenChange={setSymOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 font-semibold" aria-label="Change symbol (/)">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            {shortSymbol(cell.symbol)}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 p-2">
          <SymbolSearch autoFocus onPick={(s) => {
            setCell(active, { symbol: s });
            setSymOpen(false);
          }} placeholder="Symbol, index, future or option…" />
          <p className="mt-2 text-[11px] text-muted-foreground">Tip: press / on the chart to search.</p>
        </PopoverContent>
      </Popover>
      <Popover open={cmpOpen} onOpenChange={setCmpOpen}>
        <Tooltip content="Compare symbol (percent scale)">
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Compare symbol">
              <Plus />
            </Button>
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent align="start" className="w-80 p-2">
          <SymbolSearch autoFocus placeholder="Compare with…" onPick={(s) => {
            if (s !== cell.symbol && !cell.compare.includes(s)) setCell(active, { compare: [...cell.compare, s].slice(0, 5) });
            setCmpOpen(false);
          }} />
        </PopoverContent>
      </Popover>
      <span className="mx-1 h-5 w-px bg-border" />
      {QUICK_TF.map((t) => (
        <button key={t} onClick={() => setCell(active, { tf: t })} className={cn("h-8 rounded px-1.5 text-xs font-medium", cell.tf === t ? "text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground")} aria-pressed={cell.tf === t} aria-label={`Timeframe ${tfLabel(t)}`}>
          {tfLabel(t)}
        </button>
      ))}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className={ib} aria-label="More timeframes">
            {!QUICK_TF.includes(cell.tf) && <span className="text-primary">{tfLabel(cell.tf)}</span>}
            <ChevronDown className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-96 w-44 overflow-y-auto">
          {["Minutes", "Hours", "Days"].map((g) => (
            <React.Fragment key={g}>
              <DropdownMenuLabel>{g}</DropdownMenuLabel>
              {TIMEFRAMES.filter((t) => t.group === g).map((t) => (
                <DropdownMenuItem key={t.code} onSelect={() => setCell(active, { tf: t.code })}>
                  <span className="flex-1">{t.label}</span>
                  {cell.tf === t.code && <Check className="h-3.5 w-3.5" />}
                </DropdownMenuItem>
              ))}
            </React.Fragment>
          ))}
          <DropdownMenuSeparator />
          <form
            className="flex gap-1 p-1"
            onSubmit={(e) => {
              e.preventDefault();
              const m = parseInt(custom, 10);
              if (m >= 1 && m <= 375) setCell(active, { tf: String(m) });
              else toast.error("Custom timeframe: 1–375 minutes");
            }}
          >
            <input className="h-7 w-full rounded border bg-background px-2 text-xs" placeholder="Custom minutes" inputMode="numeric" value={custom} onChange={(e) => setCustom(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
            <button className="rounded bg-primary px-2 text-xs text-primary-foreground">Go</button>
          </form>
        </DropdownMenuContent>
      </DropdownMenu>
      <span className="mx-1 h-5 w-px bg-border" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className={ib} aria-label="Chart type">
            <CandlestickChart className="h-4 w-4" />
            <span className="hidden lg:inline">{CHART_TYPES.find((t) => t.id === cell.type)?.label}</span>
            <ChevronDown className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-48">
          {CHART_TYPES.map((t) => (
            <DropdownMenuItem key={t.id} onSelect={() => setCell(active, { type: t.id })}>
              <span className="flex-1">{t.label}</span>
              {cell.type === t.id && <Check className="h-3.5 w-3.5" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <Button variant="ghost" size="sm" className={ib} onClick={onIndicators} aria-label="Indicators">
        <span className="font-serif italic">ƒx</span>
        <span className="hidden sm:inline">Indicators</span>
      </Button>
      <Tooltip content="Create price alert">
        <Button variant="ghost" size="icon-sm" onClick={onAlert} aria-label="Create price alert">
          <Bell />
        </Button>
      </Tooltip>
      <Tooltip content="Bar replay">
        <Button variant="ghost" size="icon-sm" onClick={() => cellApis.get(active)?.startReplay()} aria-label="Bar replay">
          <Rewind />
        </Button>
      </Tooltip>
      <span className="mx-1 h-5 w-px bg-border" />
      <Tooltip content="Undo drawing (Ctrl+Z)">
        <Button variant="ghost" size="icon-sm" disabled={!canUndo} onClick={undo} aria-label="Undo">
          <Undo2 />
        </Button>
      </Tooltip>
      <Tooltip content="Redo (Ctrl+Y)">
        <Button variant="ghost" size="icon-sm" disabled={!canRedo} onClick={redo} aria-label="Redo">
          <Redo2 />
        </Button>
      </Tooltip>
      <div className="ml-auto flex items-center gap-0.5 pl-2">
        {source && (
          <Tooltip content={source.live ? "Prices stream from Upstox in real time" : source.detail ?? "Simulated market"}>
            {isAdmin && !source.live ? (
              <Link href="/admin?tab=market-data" className="mr-1 flex items-center gap-1 whitespace-nowrap rounded-full bg-warning/15 px-2 py-0.5 text-[11px] font-medium text-warning">
                <span className="h-1.5 w-1.5 rounded-full bg-warning" /> Simulated · connect Upstox
              </Link>
            ) : (
              <span className={cn("mr-1 flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium", source.live ? "bg-profit/15 text-profit" : "bg-warning/15 text-warning")}>
                <span className={cn("h-1.5 w-1.5 rounded-full", source.live ? "animate-pulse bg-profit" : "bg-warning")} /> {source.live ? "Live · Upstox" : "Simulated data"}
              </span>
            )}
          </Tooltip>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Chart grid layout">
              <LayoutGrid />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>Charts on screen</DropdownMenuLabel>
            {(["1", "2h", "2v", "3", "4"] as GridKind[]).map((g) => (
              <DropdownMenuItem key={g} onSelect={() => setGrid(g)}>
                <span className="flex-1">{g === "1" ? "1 chart" : g === "2h" ? "2 side by side" : g === "2v" ? "2 stacked" : g === "3" ? "3 (1 + 2)" : "4 (2 × 2)"}</span>
                {grid === g && <Check className="h-3.5 w-3.5" />}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Sync across charts</DropdownMenuLabel>
            {(
              [
                ["symbol", "Symbol"],
                ["interval", "Timeframe"],
                ["crosshair", "Crosshair"],
              ] as const
            ).map(([k, label]) => (
              <DropdownMenuItem key={k} onSelect={(e) => {
                e.preventDefault();
                setLayout((l) => ({ ...l, sync: { ...l.sync, [k]: !l.sync[k] } }));
              }}>
                <span className="flex-1">{label}</span>
                {sync[k] && <Check className="h-3.5 w-3.5" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className={cn(ib, "max-w-[180px]")} aria-label="Chart layouts">
              <span className="truncate">{layoutName}</span>
              <span className={cn("text-[10px]", saveState === "error" ? "text-loss" : "text-muted-foreground")}>
                {saveState === "saving" ? "saving…" : saveState === "saved" ? "saved" : saveState === "error" ? "not saved" : ""}
              </span>
              <ChevronDown className="h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel>Layouts</DropdownMenuLabel>
            {layouts.map((l) => (
              <DropdownMenuItem key={l.id} onSelect={() => onLayoutAction({ kind: "switch", id: l.id })}>
                <span className="flex-1 truncate">{l.name}</span>
                {l.is_default && <span className="text-[10px] text-muted-foreground">default</span>}
                {l.id === layoutId && <Check className="h-3.5 w-3.5" />}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onLayoutAction({ kind: "new" })}>New layout</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onLayoutAction({ kind: "saveas" })}>Save a copy as…</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onLayoutAction({ kind: "rename" })}>Rename…</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onLayoutAction({ kind: "default" })}>Open this layout by default</DropdownMenuItem>
            <DropdownMenuItem className="text-loss" onSelect={() => onLayoutAction({ kind: "delete" })} disabled={layouts.length <= 1}>
              Delete layout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Tooltip content="Settings">
          <Button variant="ghost" size="icon-sm" onClick={onSettings} aria-label="Chart settings">
            <Settings2 />
          </Button>
        </Tooltip>
        <Tooltip content="Download screenshot (PNG)">
          <Button variant="ghost" size="icon-sm" onClick={screenshot} aria-label="Screenshot">
            <Camera />
          </Button>
        </Tooltip>
        <Tooltip content={fs ? "Exit full screen" : "Full screen"}>
          <Button variant="ghost" size="icon-sm" onClick={fullscreen} aria-label="Full screen" className="hidden sm:inline-flex">
            {fs ? <Minimize2 /> : <Maximize2 />}
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}

function BottomBar() {
  const active = useTerminal((s) => s.layout.active);
  const cell = useTerminal((s) => s.layout.cells[s.layout.active]!);
  const setCell = useTerminal((s) => s.setCell);
  const [date, setDate] = React.useState("");
  const toggle = "h-6 rounded px-1.5 text-[11px] font-medium";
  return (
    <div className="flex h-8 shrink-0 items-center gap-0.5 overflow-x-auto border-t bg-card px-2 text-[11px]">
      {RANGES.map((r) => (
        <button key={r.id} className={cn(toggle, "text-muted-foreground hover:bg-muted hover:text-foreground")} onClick={() => cellApis.get(active)?.showRange(r.id)} title={`Show ${r.label} (${tfLabel(r.tf)} bars)`} aria-label={`Show range ${r.label}`}>
          {r.label}
        </button>
      ))}
      <span className="mx-1 h-4 w-px bg-border" />
      <form
        className="flex items-center gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          if (date) cellApis.get(active)?.gotoDate(date);
        }}
      >
        <input type="date" aria-label="Go to date" className="h-6 rounded border bg-background px-1 text-[11px]" value={date} onChange={(e) => setDate(e.target.value)} />
        <button className={cn(toggle, "text-muted-foreground hover:bg-muted hover:text-foreground")}>Go to</button>
      </form>
      <div className="ml-auto flex items-center gap-0.5 pl-2">
        <span className="mr-2 hidden text-muted-foreground sm:inline">
          <Clock />
        </span>
        <button className={cn(toggle, cell.percent ? "text-primary" : "text-muted-foreground hover:bg-muted")} aria-pressed={cell.percent} onClick={() => setCell(active, { percent: !cell.percent, log: false })}>
          %
        </button>
        <button className={cn(toggle, cell.log ? "text-primary" : "text-muted-foreground hover:bg-muted")} aria-pressed={cell.log} onClick={() => setCell(active, { log: !cell.log, percent: false })}>
          log
        </button>
        <button className={cn(toggle, "text-muted-foreground hover:bg-muted")} onClick={() => cellApis.get(active)?.fit()}>
          auto
        </button>
      </div>
    </div>
  );
}

const PANELS = [
  { id: "watchlist", label: "Watchlist", icon: List },
  { id: "details", label: "Quote & depth", icon: Info },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "objects", label: "Objects", icon: Shapes },
] as const;

function RightPanel({ onNewAlert }: { onNewAlert: () => void }) {
  const panel = useTerminal((s) => s.layout.panel);
  const setLayout = useTerminal((s) => s.setLayout);
  const set = (p: LayoutState["panel"]) => setLayout((l) => ({ ...l, panel: l.panel === p ? null : p }));
  return (
    <>
      {panel && (
        <div className="hidden w-72 shrink-0 flex-col border-l bg-card lg:flex">
          <div className="flex h-9 items-center justify-between border-b px-3 text-xs font-medium">
            {PANELS.find((p) => p.id === panel)?.label}
            <button aria-label="Close panel" className="rounded p-0.5 text-muted-foreground hover:bg-muted" onClick={() => set(null)}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {panel === "watchlist" && <WatchlistPanel />}
          {panel === "details" && <DetailsPanel />}
          {panel === "alerts" && <AlertsPanel onNew={onNewAlert} />}
          {panel === "objects" && <ObjectsPanel />}
        </div>
      )}
      <div className="hidden w-10 shrink-0 flex-col items-center gap-1 border-l bg-card py-1 lg:flex" role="toolbar" aria-label="Panels" aria-orientation="vertical">
        {PANELS.map((p) => (
          <Tooltip key={p.id} side="left" content={p.label}>
            <button aria-label={p.label} aria-pressed={panel === p.id} onClick={() => set(p.id)} className={cn("flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground", panel === p.id && "bg-primary/15 text-primary")}>
              <p.icon className="h-4 w-4" />
            </button>
          </Tooltip>
        ))}
      </div>
    </>
  );
}

function Grid() {
  const grid = useTerminal((s) => s.layout.grid);
  const active = useTerminal((s) => s.layout.active);
  const n = GRID_CELLS[grid];
  const cls = { "1": "grid-cols-1 grid-rows-1", "2h": "grid-cols-1 md:grid-cols-2 grid-rows-1", "2v": "grid-cols-1 grid-rows-1 md:grid-rows-2", "3": "grid-cols-1 md:grid-cols-2 md:grid-rows-2", "4": "grid-cols-1 md:grid-cols-2 md:grid-rows-2" }[grid];
  return (
    <div className={cn("grid min-h-0 min-w-0 flex-1 gap-px bg-border", cls)}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className={cn("min-h-0 min-w-0", grid === "3" && i === 0 && "md:row-span-2", i !== active && "hidden md:block")}>
          <ChartCell index={i} active={n > 1 && i === active} compact={n > 2} />
        </div>
      ))}
    </div>
  );
}

/** Load the user's default layout (creating one on first visit) and auto-save every change. */
function useLayouts() {
  const params = useSearchParams();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["chart-layouts"], queryFn: () => apiJson<LayoutRow[]>("/api/charts/layouts") });
  const loaded = React.useRef(false);
  const [ready, setReady] = React.useState(false);

  const open = React.useCallback(async (id: number) => {
    const row = await apiJson<LayoutRow & { state: unknown }>(`/api/charts/layouts/${id}`);
    useTerminal.getState().load(row.id, row.name, row.state);
  }, []);

  React.useEffect(() => {
    if (!list.data || loaded.current) return;
    loaded.current = true;
    void (async () => {
      try {
        if (list.data.length === 0) {
          const state = defaultLayout();
          const row = await apiJson<LayoutRow>("/api/charts/layouts", { method: "POST", body: JSON.stringify({ name: "My charts", state }) });
          useTerminal.getState().load(row.id, row.name, state);
          void qc.invalidateQueries({ queryKey: ["chart-layouts"] });
        } else {
          await open((list.data.find((l) => l.is_default) ?? list.data[0]!).id);
        }
      } catch (e) {
        toast.error(`Could not load your chart layout: ${(e as Error).message}`);
        useTerminal.getState().load(null, "Unsaved layout", defaultLayout());
      }
      const sym = params.get("symbol");
      const tf = params.get("tf");
      if (sym || tf) {
        const st = useTerminal.getState();
        st.setCell(st.layout.active, { ...(sym ? { symbol: sym } : {}), ...(tf ? { tf } : {}) });
        // apply a deep link once; afterwards the saved layout is the source of truth (reloads keep your changes)
        window.history.replaceState(null, "", window.location.pathname);
      }
      setReady(true);
    })();
  }, [list.data, open, params, qc]);

  // auto-save (debounced)
  const dirty = useTerminal((s) => s.dirty);
  const layoutId = useTerminal((s) => s.layoutId);
  const flush = React.useCallback(async () => {
    const st = useTerminal.getState();
    if (!st.layoutId) return;
    st.setSaveState("saving");
    try {
      await apiJson(`/api/charts/layouts/${st.layoutId}`, { method: "PUT", body: JSON.stringify({ state: st.layout }) });
      useTerminal.getState().setSaveState("saved");
    } catch (e) {
      useTerminal.getState().setSaveState("error");
      toast.error(`Layout not saved: ${(e as Error).message}`, { id: "layout-save" });
    }
  }, []);
  React.useEffect(() => {
    if (!ready || !dirty || !layoutId) return;
    const h = setTimeout(() => void flush(), 1200);
    return () => clearTimeout(h);
  }, [dirty, ready, layoutId, flush]);

  return { list: list.data ?? [], ready, open, flush, refresh: () => qc.invalidateQueries({ queryKey: ["chart-layouts"] }) };
}

export function ChartsTerminal() {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const { list, ready, open, flush, refresh } = useLayouts();
  const [indOpen, setIndOpen] = React.useState(false);
  const [alertOpen, setAlertOpen] = React.useState(false);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [nameDlg, setNameDlg] = React.useState<null | "rename" | "saveas" | "new">(null);
  const layoutName = useTerminal((s) => s.layoutName);

  // keyboard shortcuts
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      if (document.querySelector("[role=dialog]")) return;
      const st = useTerminal.getState();
      if (e.key === "Escape") {
        st.setTool("cursor");
        st.select(null);
      } else if ((e.key === "Delete" || e.key === "Backspace") && st.selected) {
        const list = st.layout.drawings[st.selected.symbol] ?? [];
        st.setDrawings(st.selected.symbol, list.filter((d) => d.id !== st.selected!.id));
        st.select(null);
        e.preventDefault();
      } else if ((e.ctrlKey || e.metaKey) && e.code === "KeyZ") {
        e.preventDefault();
        if (e.shiftKey) st.redo();
        else st.undo();
      } else if ((e.ctrlKey || e.metaKey) && e.code === "KeyY") {
        e.preventDefault();
        st.redo();
      } else if (e.altKey && SHORTCUTS[e.code]) {
        e.preventDefault();
        st.setTool(SHORTCUTS[e.code]!);
      } else if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        window.dispatchEvent(new Event("chart:symbol-search"));
      } else if (e.altKey && e.code === "KeyI") {
        e.preventDefault();
        setIndOpen(true);
      } else if (e.altKey && e.code === "KeyA") {
        e.preventDefault();
        setAlertOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // prefetch is per cell; persist before leaving the page
  React.useEffect(() => () => void flush(), [flush]);

  const layoutAction = async (a: { kind: "switch"; id: number } | { kind: "rename" | "saveas" | "default" | "delete" | "new" }) => {
    const st = useTerminal.getState();
    try {
      if (a.kind === "switch") {
        await flush();
        await open(a.id);
      } else if (a.kind === "rename" || a.kind === "saveas" || a.kind === "new") {
        setNameDlg(a.kind);
      } else if (a.kind === "default" && st.layoutId) {
        await apiJson(`/api/charts/layouts/${st.layoutId}`, { method: "PUT", body: JSON.stringify({ is_default: true }) });
        toast.success("This layout now opens by default");
        void refresh();
      } else if (a.kind === "delete" && st.layoutId) {
        if (!confirm(`Delete layout "${st.layoutName}" and its drawings?`)) return;
        await apiJson(`/api/charts/layouts/${st.layoutId}`, { method: "DELETE" });
        const next = list.find((l) => l.id !== st.layoutId);
        if (next) await open(next.id);
        void refresh();
      }
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const submitName = async (name: string) => {
    const st = useTerminal.getState();
    try {
      if (nameDlg === "rename" && st.layoutId) {
        await apiJson(`/api/charts/layouts/${st.layoutId}`, { method: "PUT", body: JSON.stringify({ name }) });
        st.setLayoutMeta(st.layoutId, name);
      } else {
        await flush();
        const state = nameDlg === "new" ? defaultLayout() : st.layout;
        const row = await apiJson<LayoutRow>("/api/charts/layouts", { method: "POST", body: JSON.stringify({ name, state }) });
        st.load(row.id, row.name, state);
      }
      void refresh();
      setNameDlg(null);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <div ref={rootRef} data-chart-terminal className="flex h-full min-h-0 flex-col overflow-hidden border bg-background md:rounded-lg">
      <TopToolbar rootRef={rootRef} onIndicators={() => setIndOpen(true)} onAlert={() => setAlertOpen(true)} onSettings={() => setSettingsOpen(true)} layouts={list} onLayoutAction={(a) => void layoutAction(a)} />
      <div className="flex min-h-0 flex-1">
        <DrawingToolbar />
        {ready ? <Grid /> : <div className="flex-1 animate-pulse bg-card" aria-busy="true" />}
        <RightPanel onNewAlert={() => setAlertOpen(true)} />
      </div>
      <BottomBar />
      <IndicatorsDialog open={indOpen} onOpenChange={setIndOpen} />
      <AlertDialog open={alertOpen} onOpenChange={setAlertOpen} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <RenameDialog
        open={nameDlg != null}
        onOpenChange={(o) => !o && setNameDlg(null)}
        initial={nameDlg === "rename" ? layoutName : nameDlg === "saveas" ? `${layoutName} (copy)` : "New layout"}
        title={nameDlg === "rename" ? "Rename layout" : nameDlg === "saveas" ? "Save a copy" : "New layout"}
        onSubmit={(n) => void submitName(n)}
      />
    </div>
  );
}

