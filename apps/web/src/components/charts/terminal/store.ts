"use client";
/**
 * Charts terminal state: the persisted layout (grid, per-chart symbol/timeframe/style/indicators, drawings per
 * symbol, settings) plus transient UI state (active tool, selection, crosshair sync). The persisted part is
 * auto-saved to the user's chart layout on the server.
 */
import { create } from "zustand";
import type { Drawing, DrawingType } from "@/lib/chart/drawings";
import { defaultParams, INDICATOR_BY_ID, type Params } from "@/lib/chart/indicators";

export type ChartType = "candles" | "hollow" | "heikin" | "bars" | "line" | "area" | "baseline" | "renko" | "linebreak";
export type GridKind = "1" | "2h" | "2v" | "3" | "4";

export const CHART_TYPES: { id: ChartType; label: string }[] = [
  { id: "candles", label: "Candles" },
  { id: "hollow", label: "Hollow candles" },
  { id: "heikin", label: "Heikin Ashi" },
  { id: "bars", label: "Bars (OHLC)" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
  { id: "baseline", label: "Baseline" },
  { id: "renko", label: "Renko (ATR box)" },
  { id: "linebreak", label: "Line break (3)" },
];

export const GRID_CELLS: Record<GridKind, number> = { "1": 1, "2h": 2, "2v": 2, "3": 3, "4": 4 };

export interface IndicatorState {
  uid: string;
  id: string;
  params: Params;
  visible: boolean;
}

export interface CellState {
  symbol: string;
  tf: string;
  type: ChartType;
  indicators: IndicatorState[];
  compare: string[];
  log: boolean;
  percent: boolean;
}

export interface Settings {
  upColor: string;
  downColor: string;
  grid: boolean;
  watermark: boolean;
  magnet: boolean;
}

export interface LayoutState {
  v: 1;
  grid: GridKind;
  cells: CellState[];
  active: number;
  sync: { symbol: boolean; interval: boolean; crosshair: boolean };
  drawings: Record<string, Drawing[]>;
  settings: Settings;
  watchlistId: number | null;
  panel: "watchlist" | "details" | "alerts" | "objects" | null;
}

export type Tool = DrawingType | "cursor";

/** Stable empty list for selectors (a fresh [] on every call would re-render forever). */
export const NO_DRAWINGS: Drawing[] = [];

const uid = () => Math.random().toString(36).slice(2, 9);

export function indicator(id: string, params?: Params): IndicatorState {
  const def = INDICATOR_BY_ID[id];
  return { uid: uid(), id, params: { ...(def ? defaultParams(def) : {}), ...(params ?? {}) }, visible: true };
}

export function newCell(symbol = "NSE_INDEX:NIFTY", tf = "15"): CellState {
  return { symbol, tf, type: "candles", indicators: [indicator("VOL")], compare: [], log: false, percent: false };
}

export function defaultLayout(): LayoutState {
  return {
    v: 1,
    grid: "1",
    cells: [{ ...newCell("NSE_INDEX:NIFTY", "15"), indicators: [indicator("VOL"), indicator("EMA", { length: 20 }), indicator("RSI")] }],
    active: 0,
    sync: { symbol: false, interval: false, crosshair: true },
    drawings: {},
    settings: { upColor: "#089981", downColor: "#f23645", grid: true, watermark: true, magnet: false },
    watchlistId: null,
    panel: "watchlist",
  };
}

/** Accept a saved layout from any earlier version, filling gaps with defaults. */
export function normalizeLayout(raw: unknown): LayoutState {
  const d = defaultLayout();
  if (!raw || typeof raw !== "object") return d;
  const r = raw as Partial<LayoutState>;
  const cells = Array.isArray(r.cells) && r.cells.length ? r.cells.map((c) => ({ ...newCell(), ...c, indicators: (c.indicators ?? []).filter((i) => INDICATOR_BY_ID[i.id]) })) : d.cells;
  const grid = r.grid && r.grid in GRID_CELLS ? r.grid : "1";
  while (cells.length < GRID_CELLS[grid]) cells.push(newCell(cells[0]!.symbol, cells[0]!.tf));
  return {
    ...d,
    ...r,
    v: 1,
    grid,
    cells,
    active: Math.min(Math.max(0, r.active ?? 0), GRID_CELLS[grid] - 1),
    sync: { ...d.sync, ...(r.sync ?? {}) },
    settings: { ...d.settings, ...(r.settings ?? {}) },
    drawings: r.drawings && typeof r.drawings === "object" ? r.drawings : {},
  };
}

interface History {
  past: Record<string, Drawing[]>[];
  future: Record<string, Drawing[]>[];
}

interface TerminalStore {
  layout: LayoutState;
  layoutId: number | null;
  layoutName: string;
  saveState: "idle" | "saving" | "saved" | "error";
  dirty: number;
  tool: Tool;
  selected: { symbol: string; id: string } | null;
  crosshair: { time: number | null; source: number } | null;
  history: History;
  load: (id: number | null, name: string, state: unknown) => void;
  setLayout: (fn: (l: LayoutState) => LayoutState, persist?: boolean) => void;
  setCell: (i: number, patch: Partial<CellState>) => void;
  setActive: (i: number) => void;
  setGrid: (g: GridKind) => void;
  setTool: (t: Tool) => void;
  select: (s: { symbol: string; id: string } | null) => void;
  setDrawings: (symbol: string, list: Drawing[], record?: boolean) => void;
  undo: () => void;
  redo: () => void;
  setCrosshair: (c: { time: number | null; source: number } | null) => void;
  setSaveState: (s: TerminalStore["saveState"]) => void;
  setLayoutMeta: (id: number | null, name: string) => void;
}

export const useTerminal = create<TerminalStore>((set, get) => ({
  layout: defaultLayout(),
  layoutId: null,
  layoutName: "My charts",
  saveState: "idle",
  dirty: 0,
  tool: "cursor",
  selected: null,
  crosshair: null,
  history: { past: [], future: [] },
  load: (id, name, state) => set({ layout: normalizeLayout(state), layoutId: id, layoutName: name, dirty: 0, history: { past: [], future: [] }, selected: null }),
  setLayout: (fn, persist = true) => set((s) => ({ layout: fn(s.layout), dirty: persist ? s.dirty + 1 : s.dirty })),
  setCell: (i, patch) => {
    const { layout } = get();
    const cells = layout.cells.map((c, j) => {
      if (j === i) return { ...c, ...patch };
      // linked charts follow the active chart's symbol / interval
      const p: Partial<CellState> = {};
      if (layout.sync.symbol && patch.symbol) p.symbol = patch.symbol;
      if (layout.sync.interval && patch.tf) p.tf = patch.tf;
      return { ...c, ...p };
    });
    set((s) => ({ layout: { ...layout, cells }, dirty: s.dirty + 1 }));
  },
  setActive: (i) => set((s) => (s.layout.active === i ? s : { layout: { ...s.layout, active: i }, dirty: s.dirty + 1 })),
  setGrid: (g) =>
    set((s) => {
      const cells = s.layout.cells.slice(0, Math.max(GRID_CELLS[g], 1));
      while (cells.length < GRID_CELLS[g]) cells.push({ ...newCell(cells[0]?.symbol, cells[0]?.tf), indicators: [indicator("VOL")] });
      return { layout: { ...s.layout, grid: g, cells, active: Math.min(s.layout.active, GRID_CELLS[g] - 1) }, dirty: s.dirty + 1 };
    }),
  setTool: (t) => set({ tool: t }),
  select: (sel) => set({ selected: sel }),
  setDrawings: (symbol, list, record = true) =>
    set((s) => {
      const drawings = { ...s.layout.drawings, [symbol]: list };
      if (!list.length) delete drawings[symbol];
      const history = record ? { past: [...s.history.past.slice(-49), s.layout.drawings], future: [] } : s.history;
      return { layout: { ...s.layout, drawings }, history, dirty: s.dirty + 1 };
    }),
  undo: () =>
    set((s) => {
      const prev = s.history.past.at(-1);
      if (!prev) return s;
      return { layout: { ...s.layout, drawings: prev }, history: { past: s.history.past.slice(0, -1), future: [s.layout.drawings, ...s.history.future] }, dirty: s.dirty + 1, selected: null };
    }),
  redo: () =>
    set((s) => {
      const next = s.history.future[0];
      if (!next) return s;
      return { layout: { ...s.layout, drawings: next }, history: { past: [...s.history.past, s.layout.drawings], future: s.history.future.slice(1) }, dirty: s.dirty + 1, selected: null };
    }),
  setCrosshair: (c) => set({ crosshair: c }),
  setSaveState: (saveState) => set({ saveState }),
  setLayoutMeta: (id, name) => set({ layoutId: id, layoutName: name }),
}));

/** Imperative handles registered by each chart cell (screenshot, ranges). */
export interface CellApi {
  screenshot: () => HTMLCanvasElement | null;
  fit: () => void;
  showRange: (range: string) => void;
  gotoDate: (iso: string) => void;
  lastPrice: () => number | null;
  startReplay: () => void;
}

export const cellApis = new Map<number, CellApi>();

export const RANGES: { id: string; label: string; tf: string; seconds: number | "ytd" | "all" }[] = [
  { id: "1D", label: "1D", tf: "1", seconds: 86400 },
  { id: "5D", label: "5D", tf: "5", seconds: 7 * 86400 },
  { id: "1M", label: "1M", tf: "30", seconds: 31 * 86400 },
  { id: "3M", label: "3M", tf: "60", seconds: 92 * 86400 },
  { id: "6M", label: "6M", tf: "120", seconds: 183 * 86400 },
  { id: "YTD", label: "YTD", tf: "D", seconds: "ytd" },
  { id: "1Y", label: "1Y", tf: "D", seconds: 366 * 86400 },
  { id: "5Y", label: "5Y", tf: "W", seconds: 5 * 366 * 86400 },
  { id: "All", label: "All", tf: "M", seconds: "all" },
];
