"use client";
/**
 * One chart of the terminal: bars (with history paging), live ticks, chart types, indicators in panes, compare
 * symbols, drawings (create / select / drag / edit), price-alert lines, bar replay and crosshair sync.
 */
import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import {
  AreaSeries,
  BarSeries,
  BaselineSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createTextWatermark,
  CrosshairMode,
  HistogramSeries,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ITextWatermarkPluginApi,
  LineSeries,
  LineStyle,
  LineType,
  type Logical,
  type MouseEventParams,
  PriceScaleMode,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { AlertTriangle, Eye, EyeOff, Loader2, Pause, Play, RotateCcw, Settings2, SkipBack, SkipForward, X } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";
import { useRealtime } from "@/hooks/use-realtime";
import { apiJson } from "@/lib/api";
import { type Anchor, type Drawing, DrawingLayer, newId, TOOL_POINTS } from "@/lib/chart/drawings";
import { atr, type BarsInput, INDICATOR_BY_ID, type IndicatorDef, indicatorLabel, type Out } from "@/lib/chart/indicators";
import {
  type ApiBar,
  applyTick,
  type Bar,
  barSeconds,
  exchangeOf,
  fmtPrice,
  fmtVolume,
  heikinAshi,
  lineBreak,
  makeMapper,
  mergeBars,
  renko,
  tfInfo,
  tfLabel,
  toBars,
} from "@/lib/chart/series";
import { cn } from "@/lib/utils";
import { cssHsl } from "../theme";
import { type CellApi, cellApis, type CellState, RANGES, useTerminal } from "./store";

const PAGE = 600;
const EMPTY: Drawing[] = [];
const COMPARE_COLORS = ["#ff9800", "#2962ff", "#e91e63", "#00bcd4", "#8e24aa"];

export interface BarsResp {
  symbol: string;
  tf: string;
  label: string;
  intraday: boolean;
  exchange: string;
  bars: ApiBar[];
  has_more: boolean;
  next_to: string | null;
  source: { provider: string; live: boolean; label: string; detail: string | null; last_error: string | null };
}

interface IndSeries {
  uid: string;
  def: IndicatorDef;
  plot: string;
  kind: string;
  series: ISeriesApi<SeriesType>;
}

export function barsUrl(symbol: string, tf: string, to?: string | null, count = PAGE) {
  return `/api/charts/bars?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}&count=${count}${to ? `&to=${encodeURIComponent(to)}` : ""}`;
}

function useBars(symbol: string, tf: string) {
  return useInfiniteQuery({
    queryKey: ["chart-bars", symbol, tf],
    queryFn: ({ pageParam }) => apiJson<BarsResp>(barsUrl(symbol, tf, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.has_more ? last.next_to : undefined),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}

function pal(dark: boolean) {
  return {
    bg: cssHsl("card"),
    text: cssHsl("muted-foreground"),
    grid: dark ? "rgba(120,123,134,0.12)" : "rgba(120,123,134,0.16)",
    border: cssHsl("border"),
    fg: cssHsl("foreground"),
  };
}

function hexA(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function niceBox(x: number): number {
  if (!(x > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= x) return m * p;
  return 10 * p;
}

export function shortSymbol(s: string) {
  return s.split(":").slice(1).join(":") || s;
}

export function ChartCell({ index, active, compact }: { index: number; active: boolean; compact?: boolean }) {
  const cell = useTerminal((s) => s.layout.cells[index]!) as CellState;
  const settings = useTerminal((s) => s.layout.settings);
  const syncCrosshair = useTerminal((s) => s.layout.sync.crosshair);
  const drawings = useTerminal((s) => s.layout.drawings[cell.symbol] ?? EMPTY);
  const tool = useTerminal((s) => s.tool);
  const selected = useTerminal((s) => s.selected);
  const crosshair = useTerminal((s) => s.crosshair);
  const { setCell, setActive, setTool, select, setDrawings } = useTerminal.getState();
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme !== "light";
  const tf = React.useMemo(() => tfInfo(cell.tf), [cell.tf]);
  const exchange = exchangeOf(cell.symbol);

  // ------------------------------------------------------------------ data
  const q = useBars(cell.symbol, cell.tf);
  const serverBars = React.useMemo(() => {
    const pages = q.data?.pages ?? [];
    let out: Bar[] = [];
    for (let i = pages.length - 1; i >= 0; i--) out = mergeBars(out, toBars(pages[i]!.bars));
    return out;
  }, [q.data]);
  const source = q.data?.pages[0]?.source;
  const [bars, setBars] = React.useState<Bar[]>([]);
  const keyRef = React.useRef("");
  React.useEffect(() => {
    const key = `${cell.symbol}|${cell.tf}`;
    setBars((prev) => {
      if (keyRef.current !== key || !prev.length || !serverBars.length) {
        keyRef.current = key;
        return serverBars;
      }
      const last = serverBars[serverBars.length - 1]!.time;
      const liveTail = prev.filter((b) => b.time >= last); // keep live-updated forming bars
      return [...serverBars.filter((b) => b.time < (liveTail[0]?.time ?? Infinity)), ...liveTail];
    });
  }, [serverBars, cell.symbol, cell.tf]);

  const market = useQuery({
    queryKey: ["market-status"],
    queryFn: () => apiJson<{ exchange: string; is_open: boolean }[]>("/api/market/status"),
    refetchInterval: 60_000,
  });
  const isOpen = !!market.data?.find((m) => m.exchange === (exchange === "MCX" ? "MCX" : "NSE"))?.is_open;

  // replay
  const [replay, setReplay] = React.useState<{ active: boolean; cursor: number; playing: boolean; speed: number }>({ active: false, cursor: 0, playing: false, speed: 2 });
  const replayRef = React.useRef(replay);
  replayRef.current = replay;

  // live ticks
  const prevVol = React.useRef<number | null>(null);
  const [lastTick, setLastTick] = React.useState<{ ltp: number; change_pct?: number | null } | null>(null);
  React.useEffect(() => {
    prevVol.current = null;
    setLastTick(null);
  }, [cell.symbol]);
  useRealtime({ channel: "ticks", symbols: [cell.symbol] }, (f) => {
    const t = f.data as { symbol: string; ltp: number; ts: string; volume?: number | null; change_pct?: number | null };
    if (!t || t.symbol !== cell.symbol) return;
    setLastTick({ ltp: t.ltp, change_pct: t.change_pct });
    if (replayRef.current.active || !isOpen) {
      prevVol.current = t.volume ?? prevVol.current;
      return;
    }
    setBars((prev) => applyTick(prev, t, tf, exchange, prevVol.current).bars);
    prevVol.current = t.volume ?? prevVol.current;
  });

  // compare symbols (same timeframe, first page)
  const compares = useQueries({
    queries: cell.compare.map((s) => ({ queryKey: ["chart-bars-compare", s, cell.tf], queryFn: () => apiJson<BarsResp>(barsUrl(s, cell.tf)), staleTime: 30_000 })),
  });

  // display data: replay window + chart-type transform
  const baseBars = replay.active ? bars.slice(0, Math.max(2, replay.cursor)) : bars;
  const display = React.useMemo(() => {
    if (cell.type === "heikin") return heikinAshi(baseBars);
    if (cell.type === "renko" || cell.type === "linebreak") {
      if (baseBars.length < 20) return baseBars;
      if (cell.type === "linebreak") return lineBreak(baseBars, 3);
      const input: BarsInput = { t: [], o: [], h: baseBars.map((b) => b.high), l: baseBars.map((b) => b.low), c: baseBars.map((b) => b.close), v: [], barSeconds: 60, unit: tf.unit };
      const a = atr(input, 14).at(-1) ?? baseBars.at(-1)!.close * 0.01;
      return renko(baseBars, niceBox(a ?? 1));
    }
    return baseBars;
  }, [baseBars, cell.type, tf.unit]);
  const displayRef = React.useRef(display);
  displayRef.current = display;

  const indicatorInput = React.useMemo<BarsInput>(
    () => ({ t: display.map((b) => b.time), o: display.map((b) => b.open), h: display.map((b) => b.high), l: display.map((b) => b.low), c: display.map((b) => b.close), v: display.map((b) => b.volume), barSeconds: barSeconds(tf), unit: tf.unit }),
    [display, tf],
  );
  const hasVolume = React.useMemo(() => display.some((b) => b.volume > 0), [display]);
  const outputs = React.useMemo(() => {
    const res: Record<string, Record<string, Out>> = {};
    for (const ind of cell.indicators) {
      const def = INDICATOR_BY_ID[ind.id];
      if (!def || !ind.visible) continue;
      if (!hasVolume && def.category === "Volume") continue; // indices have no traded volume
      try {
        res[ind.uid] = def.compute(indicatorInput, ind.params);
      } catch {
        // a bad parameter must not take the chart down
      }
    }
    return res;
  }, [cell.indicators, indicatorInput, hasVolume]);
  const outputsRef = React.useRef(outputs);
  outputsRef.current = outputs;

  // ------------------------------------------------------------------ chart lifecycle
  const containerRef = React.useRef<HTMLDivElement>(null);
  const chartRef = React.useRef<IChartApi | null>(null);
  const mainRef = React.useRef<ISeriesApi<SeriesType> | null>(null);
  const layerRef = React.useRef<DrawingLayer>(new DrawingLayer());
  const indRef = React.useRef<IndSeries[]>([]);
  const compareRef = React.useRef<ISeriesApi<SeriesType>[]>([]);
  const volScaleUsed = React.useRef(false);
  const watermarkRef = React.useRef<ITextWatermarkPluginApi<Time> | null>(null);
  const prevShape = React.useRef<{ first: number; len: number; type: string } | null>(null);
  const indShape = React.useRef<{ first: number; len: number } | null>(null);
  const [hover, setHover] = React.useState<number | null>(null);
  const [legendOpen, setLegendOpen] = React.useState(() => typeof window === "undefined" || window.innerWidth >= 768);
  const [mainVersion, setMainVersion] = React.useState(0);
  const [indVersion, setIndVersion] = React.useState(0);

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const p = pal(dark);
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: p.bg }, textColor: p.text, fontFamily: "Inter, system-ui, sans-serif", fontSize: 11, panes: { separatorColor: p.border, enableResize: true } },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 6, minBarSpacing: 0.5 },
      localization: { priceFormatter: (v: number) => fmtPrice(v) },
    });
    chartRef.current = chart;
    const onMove = (param: MouseEventParams<Time>) => {
      const l = param.logical;
      setHover(l == null || param.point == null ? null : Math.round(l));
      if (useTerminal.getState().layout.sync.crosshair) {
        useTerminal.getState().setCrosshair(param.point == null || param.time == null ? { time: null, source: index } : { time: param.time as number, source: index });
      }
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      mainRef.current = null;
      indRef.current = [];
      compareRef.current = [];
      watermarkRef.current = null;
      prevShape.current = null;
    };
    // the chart is created once per cell; options follow below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // theme + settings
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const p = pal(dark);
    chart.applyOptions({
      layout: { background: { type: ColorType.Solid, color: p.bg }, textColor: p.text, panes: { separatorColor: p.border } },
      grid: { vertLines: { color: settings.grid ? p.grid : "transparent" }, horzLines: { color: settings.grid ? p.grid : "transparent" } },
      crosshair: { mode: settings.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal },
      timeScale: { timeVisible: tf.unit === "min" },
    });
    layerRef.current.setTextColor(p.fg);
  }, [dark, settings.grid, settings.magnet, tf.unit]);

  // main series (recreated when the chart type or colours change)
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (mainRef.current) {
      chart.removeSeries(mainRef.current);
      mainRef.current = null;
    }
    const up = settings.upColor;
    const down = settings.downColor;
    const fmt = { type: "price" as const, precision: 2, minMove: 0.01 };
    let s: ISeriesApi<SeriesType>;
    switch (cell.type) {
      case "bars":
        s = chart.addSeries(BarSeries, { upColor: up, downColor: down, thinBars: false, priceFormat: fmt });
        break;
      case "line":
        s = chart.addSeries(LineSeries, { color: "#2962ff", lineWidth: 2, priceFormat: fmt });
        break;
      case "area":
        s = chart.addSeries(AreaSeries, { lineColor: "#2962ff", topColor: "rgba(41,98,255,0.28)", bottomColor: "rgba(41,98,255,0.02)", lineWidth: 2, priceFormat: fmt });
        break;
      case "baseline":
        s = chart.addSeries(BaselineSeries, { topLineColor: up, bottomLineColor: down, topFillColor1: hexA(up, 0.28), topFillColor2: hexA(up, 0.04), bottomFillColor1: hexA(down, 0.04), bottomFillColor2: hexA(down, 0.28), lineWidth: 2, priceFormat: fmt });
        break;
      default:
        s = chart.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down, priceFormat: fmt });
    }
    s.attachPrimitive(layerRef.current);
    mainRef.current = s;
    prevShape.current = null;
    setMainVersion((v) => v + 1);
  }, [cell.type, settings.upColor, settings.downColor]);

  // price scale mode
  React.useEffect(() => {
    chartRef.current?.priceScale("right").applyOptions({
      mode: cell.compare.length || cell.percent ? PriceScaleMode.Percentage : cell.log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
  }, [cell.log, cell.percent, cell.compare.length]);

  // watermark
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!settings.watermark) {
      watermarkRef.current?.detach();
      watermarkRef.current = null;
      return;
    }
    const lines = [{ text: `${shortSymbol(cell.symbol)} · ${tfLabel(cell.tf)}`, color: dark ? "rgba(209,212,220,0.07)" : "rgba(19,23,34,0.06)", fontSize: compact ? 28 : 44, fontStyle: "bold" }];
    const pane = chart.panes()[0];
    if (!pane) return;
    if (watermarkRef.current) watermarkRef.current.applyOptions({ lines });
    else watermarkRef.current = createTextWatermark(pane, { horzAlign: "center", vertAlign: "center", lines });
  }, [cell.symbol, cell.tf, settings.watermark, dark, compact, mainVersion]);

  // main data
  React.useEffect(() => {
    const chart = chartRef.current;
    const s = mainRef.current;
    if (!chart || !s) return;
    const toPoint = (b: Bar, i: number) => {
      const time = b.time as UTCTimestamp;
      if (cell.type === "line" || cell.type === "area" || cell.type === "baseline") return { time, value: b.close };
      if (cell.type === "hollow") {
        const prev = display[i - 1];
        const col = !prev || b.close >= prev.close ? settings.upColor : settings.downColor;
        return { time, open: b.open, high: b.high, low: b.low, close: b.close, color: b.close > b.open ? "rgba(0,0,0,0)" : col, borderColor: col, wickColor: col };
      }
      return { time, open: b.open, high: b.high, low: b.low, close: b.close };
    };
    const prev = prevShape.current;
    const first = display[0]?.time ?? 0;
    const incremental = prev && prev.type === cell.type && prev.first === first && (display.length === prev.len || display.length === prev.len + 1) && display.length > 0;
    if (incremental) {
      s.update(toPoint(display[display.length - 1]!, display.length - 1) as never);
    } else {
      const range = chart.timeScale().getVisibleLogicalRange();
      const prepended = prev && prev.type === cell.type && display.length > prev.len && first < prev.first ? display.findIndex((b) => b.time === prev.first) : -1;
      s.setData(display.map(toPoint) as never);
      if (cell.type === "baseline" && display.length) {
        const ref = display[Math.max(0, display.length - 120)]!.close;
        s.applyOptions({ baseValue: { type: "price", price: ref } } as never);
      }
      if (prepended > 0 && range) chart.timeScale().setVisibleLogicalRange({ from: (range.from + prepended) as Logical, to: (range.to + prepended) as Logical });
      else if (!prev && display.length) chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, display.length - 160) as Logical, to: (display.length + 6) as Logical });
    }
    prevShape.current = { first, len: display.length, type: cell.type };
    layerRef.current.setMapper(makeMapper(display.map((b) => b.time), barSeconds(tf)), barSeconds(tf));
  }, [display, cell.type, settings.upColor, settings.downColor, tf, mainVersion]);

  // indicators: (re)build series when the list changes
  const indKey = JSON.stringify(cell.indicators.map((i) => [i.uid, i.id, i.visible, i.params]));
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !mainRef.current) return;
    for (const r of indRef.current) chart.removeSeries(r.series);
    indRef.current = [];
    for (let i = chart.panes().length - 1; i >= 1; i--) {
      try {
        chart.removePane(i);
      } catch {
        // pane already gone
      }
    }
    let pane = 0;
    volScaleUsed.current = false;
    for (const ind of cell.indicators) {
      const def = INDICATOR_BY_ID[ind.id];
      if (!def || !ind.visible) continue;
      const isVol = def.id === "VOL";
      const target = isVol || def.overlay ? 0 : ++pane;
      const scaleId = isVol ? "vol" : "right";
      def.plots.forEach((pl, k) => {
        const common = { priceScaleId: scaleId, lastValueVisible: !isVol && k === 0 && (!def.overlay || def.category === "Moving averages"), priceLineVisible: false, title: "" };
        const fmt = isVol ? { type: "volume" as const } : { type: "price" as const, precision: 2, minMove: 0.01 };
        let s: ISeriesApi<SeriesType>;
        if (pl.kind === "histogram") s = chart.addSeries(HistogramSeries, { ...common, color: pl.color, priceFormat: fmt }, target);
        else
          s = chart.addSeries(
            LineSeries,
            {
              ...common,
              color: pl.color,
              lineWidth: (pl.width ?? 1) as 1 | 2 | 3 | 4,
              lineStyle: pl.dashed ? LineStyle.Dashed : LineStyle.Solid,
              lineType: pl.kind === "step" ? LineType.WithSteps : LineType.Simple,
              lineVisible: pl.kind !== "dots",
              pointMarkersVisible: pl.kind === "dots",
              pointMarkersRadius: pl.kind === "dots" ? 1.5 : undefined,
              crosshairMarkerVisible: pl.kind !== "dots",
              priceFormat: fmt,
              autoscaleInfoProvider: def.range ? () => ({ priceRange: { minValue: def.range![0], maxValue: def.range![1] } }) : undefined,
            },
            target,
          );
        if (k === 0 && def.levels) {
          for (const lv of def.levels) s.createPriceLine({ price: lv.value, color: lv.color ?? "rgba(120,123,134,0.55)", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
        }
        indRef.current.push({ uid: ind.uid, def, plot: pl.key, kind: pl.kind, series: s });
      });
      if (isVol) {
        volScaleUsed.current = true;
        chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
      }
    }
    const panes = chart.panes();
    const oscillators = panes.length - 1;
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? Math.max(3, oscillators * 1.4) : 1));
    indShape.current = null; // new series are empty: the next data pass must be a full setData
    setIndVersion((v) => v + 1);
  }, [indKey, mainVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  // indicator data
  React.useEffect(() => {
    const first = display[0]?.time ?? 0;
    const prev = indShape.current;
    const incremental = prev && prev.first === first && (display.length === prev.len || display.length === prev.len + 1) && display.length > 0;
    for (const r of indRef.current) {
      const out = outputs[r.uid];
      const arr = out?.[r.plot];
      if (!arr) {
        r.series.setData([]);
        continue;
      }
      const point = (i: number) => {
        const v = arr[i];
        const time = display[i]!.time as UTCTimestamp;
        if (v == null) return { time };
        const color = r.def.barColor?.(r.plot, i, out, indicatorInput);
        return color ? { time, value: v, color } : { time, value: v };
      };
      if (incremental && r.def.id !== "ICHI") r.series.update(point(display.length - 1) as never);
      else r.series.setData(display.map((_, i) => point(i)) as never);
    }
    indShape.current = { first, len: display.length };
  }, [outputs, display, indVersion, indicatorInput]);

  // compare series
  const compareKey = cell.compare.join(",") + "|" + compares.map((c) => c.dataUpdatedAt).join(",");
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const s of compareRef.current) chart.removeSeries(s);
    compareRef.current = [];
    cell.compare.forEach((sym, k) => {
      const data = compares[k]?.data;
      const s = chart.addSeries(LineSeries, { color: COMPARE_COLORS[k % COMPARE_COLORS.length], lineWidth: 2, priceScaleId: "right", lastValueVisible: true, priceLineVisible: false, title: shortSymbol(sym) });
      if (data) s.setData(toBars(data.bars).map((b) => ({ time: b.time as UTCTimestamp, value: b.close })));
      compareRef.current.push(s);
    });
  }, [compareKey, mainVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  // price alerts as dashed lines
  const alerts = useQuery({
    queryKey: ["alerts", cell.symbol],
    queryFn: () => apiJson<{ id: number; value: number; op: string; status: string; message: string }[]>(`/api/alerts?symbol=${encodeURIComponent(cell.symbol)}`),
    staleTime: 10_000,
  });
  const alertLines = React.useRef<IPriceLine[]>([]);
  React.useEffect(() => {
    const s = mainRef.current;
    if (!s) return;
    for (const l of alertLines.current) s.removePriceLine(l);
    alertLines.current = (alerts.data ?? [])
      .filter((a) => a.status === "active")
      .map((a) => s.createPriceLine({ price: a.value, color: "#f5a524", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: `Alert ${a.op === "above" ? "▲" : "▼"}` }));
  }, [alerts.data, mainVersion]);

  // lazy-load older history when scrolled to the left edge
  const qRef = React.useRef(q);
  qRef.current = q;
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const onRange = (r: { from: number; to: number } | null) => {
      const cur = qRef.current;
      if (r && r.from < 30 && cur.hasNextPage && !cur.isFetchingNextPage && !replayRef.current.active) void cur.fetchNextPage();
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    return () => chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
  }, []);

  // crosshair sync from other cells
  React.useEffect(() => {
    const chart = chartRef.current;
    const s = mainRef.current;
    if (!chart || !s || !syncCrosshair || !crosshair || crosshair.source === index) return;
    if (crosshair.time == null) {
      chart.clearCrosshairPosition();
      return;
    }
    const d = displayRef.current;
    let lo = 0;
    let hi = d.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (d[mid]!.time <= crosshair.time) lo = mid;
      else hi = mid - 1;
    }
    const b = d[lo];
    if (b) chart.setCrosshairPosition(b.close, b.time as UTCTimestamp, s);
  }, [crosshair, syncCrosshair, index]);

  // drawings -> layer
  const [draft, setDraft] = React.useState<Drawing | null>(null);
  const selId = selected?.symbol === cell.symbol ? selected.id : null;
  React.useEffect(() => {
    const list = draft && drawings.some((d) => d.id === draft.id) ? drawings.map((d) => (d.id === draft.id ? draft : d)) : drawings;
    const preview = draft && !drawings.some((d) => d.id === draft.id) ? draft : null;
    layerRef.current.set(list, selId, preview);
  }, [drawings, draft, selId, mainVersion]);

  // ------------------------------------------------------------------ drawing interactions
  const toolRef = React.useRef(tool);
  toolRef.current = tool;
  const drawingsRef = React.useRef(drawings);
  drawingsRef.current = drawings;
  const settingsRef = React.useRef(settings);
  settingsRef.current = settings;
  const symbolRef = React.useRef(cell.symbol);
  symbolRef.current = cell.symbol;
  const placing = React.useRef<{ d: Drawing; n: number } | null>(null);
  const drag = React.useRef<{ id: string; handle: number; start: Anchor; orig: Drawing } | null>(null);
  const swallow = React.useRef(false);
  const [textEdit, setTextEdit] = React.useState<{ id: string; text: string } | null>(null);
  const [editing, setEditing] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (tool === "cursor" && placing.current) {
      placing.current = null;
      setDraft(null);
    }
  }, [tool]);

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const layer = layerRef.current;
    const local = (e: { clientX: number; clientY: number }) => {
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const paneRect = () => {
      const chart = chartRef.current;
      const w = el.clientWidth - (chart?.priceScale("right").width() ?? 60);
      const h = chart?.panes()[0]?.getHeight() ?? el.clientHeight;
      return { w, h };
    };
    const snap = (a: Anchor): Anchor => {
      if (!settingsRef.current.magnet) return a;
      const m = makeMapper(displayRef.current.map((b) => b.time), barSeconds(tf));
      const l = m.timeToLogical(a.t);
      if (l == null) return a;
      const b = displayRef.current[Math.max(0, Math.min(displayRef.current.length - 1, Math.round(l)))];
      if (!b) return a;
      const p = [b.open, b.high, b.low, b.close].reduce((best, x) => (Math.abs(x - a.p) < Math.abs(best - a.p) ? x : best), b.close);
      return { t: b.time, p };
    };
    const commit = (d: Drawing) => {
      const list = drawingsRef.current;
      const exists = list.some((x) => x.id === d.id);
      setDrawings(symbolRef.current, exists ? list.map((x) => (x.id === d.id ? d : x)) : [...list, d]);
      select({ symbol: symbolRef.current, id: d.id });
    };
    const moved = (d: Drawing, handle: number, start: Anchor, a: Anchor): Drawing => {
      const pts = d.points.map((p) => ({ ...p }));
      if (handle < 0) {
        const dt = a.t - start.t;
        const dp = a.p - start.p;
        return { ...d, points: pts.map((p) => ({ t: p.t + dt, p: p.p + dp })) };
      }
      if ((d.type === "rect" || d.type === "measure") && handle >= 2) {
        if (handle === 2) {
          pts[0]!.t = a.t;
          pts[1]!.p = a.p;
        } else {
          pts[1]!.t = a.t;
          pts[0]!.p = a.p;
        }
        return { ...d, points: pts };
      }
      if ((d.type === "long" || d.type === "short") && handle === 2) {
        pts[2] = { t: pts[0]!.t, p: a.p };
        return { ...d, points: pts };
      }
      if ((d.type === "long" || d.type === "short") && handle === 0 && !pts[2]) {
        pts[2] = { t: pts[0]!.t, p: layer.positionStop(d) }; // keep the stop where it is while moving the entry
      }
      pts[handle] = a;
      return { ...d, points: pts };
    };

    const onDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      useTerminal.getState().setActive(index);
      const pos = local(e);
      const { w, h } = paneRect();
      if (pos.x < 0 || pos.x > w || pos.y < 0 || pos.y > h) return;
      const t = toolRef.current;
      if (t !== "cursor") {
        swallow.current = true;
        e.stopPropagation();
        e.preventDefault();
        const raw = layer.toAnchor(pos.x, pos.y);
        if (!raw) return;
        const a = snap(raw);
        const need = TOOL_POINTS[t];
        if (!placing.current) {
          const d: Drawing = { id: newId(), type: t, points: Array.from({ length: need }, () => ({ ...a })), color: "#2962ff", width: 2 };
          if (need === 1) {
            commit(d);
            setTool("cursor");
            if (t === "text") setTextEdit({ id: d.id, text: "" });
            return;
          }
          placing.current = { d, n: 1 };
          setDraft(d);
          return;
        }
        const cur = placing.current;
        const pts = cur.d.points.slice();
        pts[cur.n] = a;
        for (let k = cur.n + 1; k < pts.length; k++) pts[k] = a;
        const d = { ...cur.d, points: pts };
        if (cur.n + 1 >= need) {
          placing.current = null;
          setDraft(null);
          commit(d);
          setTool("cursor");
        } else {
          placing.current = { d, n: cur.n + 1 };
          setDraft(d);
        }
        return;
      }
      const hit = layer.hit(pos.x, pos.y, w);
      if (hit) {
        swallow.current = true;
        e.stopPropagation();
        e.preventDefault();
        select({ symbol: symbolRef.current, id: hit.id });
        const d = drawingsRef.current.find((x) => x.id === hit.id);
        const start = layer.toAnchor(pos.x, pos.y);
        if (d && !d.locked && start) {
          drag.current = { id: d.id, handle: hit.handle, start, orig: d };
          el.setPointerCapture?.(e.pointerId);
        }
      } else if (useTerminal.getState().selected) {
        select(null);
      }
    };
    const onMove = (e: PointerEvent) => {
      const pos = local(e);
      if (drag.current) {
        const raw = layer.toAnchor(pos.x, pos.y);
        if (!raw) return;
        const a = drag.current.handle >= 0 ? snap(raw) : raw;
        setDraft(moved(drag.current.orig, drag.current.handle, drag.current.start, a));
        return;
      }
      if (placing.current) {
        const raw = layer.toAnchor(pos.x, pos.y);
        if (!raw) return;
        const a = snap(raw);
        const cur = placing.current;
        const pts = cur.d.points.slice();
        for (let k = cur.n; k < pts.length; k++) pts[k] = a;
        const d = { ...cur.d, points: pts };
        placing.current = { d, n: cur.n };
        setDraft(d);
        return;
      }
      if (toolRef.current === "cursor") {
        const { w } = paneRect();
        const hit = layer.hit(pos.x, pos.y, w);
        layer.setHovered(hit?.id ?? null);
        el.style.cursor = hit ? (hit.handle >= 0 ? "grab" : "move") : "";
      } else {
        el.style.cursor = "crosshair";
      }
    };
    const onUp = () => {
      swallow.current = false;
      if (drag.current) {
        const id = drag.current.id;
        drag.current = null;
        setDraft((cur) => {
          if (cur && cur.id === id) commit(cur);
          return null;
        });
      }
    };
    const block = (e: Event) => {
      if (swallow.current) e.stopPropagation();
    };
    const onDbl = (e: MouseEvent) => {
      const pos = local(e);
      const { w } = paneRect();
      const hit = layer.hit(pos.x, pos.y, w);
      if (hit) {
        e.stopPropagation();
        select({ symbol: symbolRef.current, id: hit.id });
        setEditing(hit.id);
      }
    };
    el.addEventListener("pointerdown", onDown, true);
    el.addEventListener("mousedown", block, true);
    el.addEventListener("touchstart", block, true);
    el.addEventListener("dblclick", onDbl, true);
    el.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown, true);
      el.removeEventListener("mousedown", block, true);
      el.removeEventListener("touchstart", block, true);
      el.removeEventListener("dblclick", onDbl, true);
      el.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [index, tf, setDrawings, select, setTool]);

  // ------------------------------------------------------------------ replay timer
  React.useEffect(() => {
    if (!replay.active || !replay.playing) return;
    const h = setInterval(() => {
      setReplay((r) => (r.cursor >= bars.length ? { ...r, playing: false } : { ...r, cursor: r.cursor + 1 }));
    }, 1000 / replay.speed);
    return () => clearInterval(h);
  }, [replay.active, replay.playing, replay.speed, bars.length]);

  // ------------------------------------------------------------------ imperative API
  const pendingRange = React.useRef<string | null>(null);
  const applyRange = React.useCallback((id: string) => {
    const chart = chartRef.current;
    const d = displayRef.current;
    const r = RANGES.find((x) => x.id === id);
    if (!chart || !r || d.length < 2) return false;
    if (r.seconds === "all") {
      if (qRef.current.hasNextPage) {
        void qRef.current.fetchNextPage();
        return false;
      }
      chart.timeScale().fitContent();
      return true;
    }
    const last = d[d.length - 1]!.time;
    const from = r.seconds === "ytd" ? Date.UTC(new Date(last * 1000).getUTCFullYear(), 0, 1) / 1000 : last - r.seconds;
    if (from < d[0]!.time && qRef.current.hasNextPage) {
      void qRef.current.fetchNextPage();
      return false;
    }
    chart.timeScale().setVisibleRange({ from: Math.max(from, d[0]!.time) as UTCTimestamp, to: last as UTCTimestamp });
    return true;
  }, []);
  React.useEffect(() => {
    if (!pendingRange.current || !display.length || q.isFetching) return;
    if (applyRange(pendingRange.current)) pendingRange.current = null;
  }, [display, q.isFetching, applyRange]);

  const pendingDate = React.useRef<number | null>(null);
  const applyDate = React.useCallback((t: number) => {
    const chart = chartRef.current;
    const d = displayRef.current;
    if (!chart || !d.length) return false;
    if (t < d[0]!.time && qRef.current.hasNextPage) {
      void qRef.current.fetchNextPage();
      return false;
    }
    const step = barSeconds(tf);
    chart.timeScale().setVisibleRange({ from: (t - 60 * step) as UTCTimestamp, to: (t + 60 * step) as UTCTimestamp });
    return true;
  }, [tf]);
  React.useEffect(() => {
    if (pendingDate.current == null || !display.length || q.isFetching) return;
    if (applyDate(pendingDate.current)) pendingDate.current = null;
  }, [display, q.isFetching, applyDate]);

  React.useEffect(() => {
    const api: CellApi = {
      screenshot: () => chartRef.current?.takeScreenshot(true, false) ?? null,
      fit: () => chartRef.current?.timeScale().fitContent(),
      showRange: (id) => {
        const r = RANGES.find((x) => x.id === id);
        if (!r) return;
        pendingRange.current = id;
        if (useTerminal.getState().layout.cells[index]!.tf !== r.tf) setCell(index, { tf: r.tf });
        else if (applyRange(id)) pendingRange.current = null;
      },
      gotoDate: (iso) => {
        const [y, m, dd] = iso.split("-").map(Number);
        if (!y || !m || !dd) return;
        const t = Date.UTC(y, m - 1, dd) / 1000 + (tf.unit === "min" ? 555 * 60 : 0);
        pendingDate.current = t;
        if (applyDate(t)) pendingDate.current = null;
      },
      lastPrice: () => lastTick?.ltp ?? displayRef.current.at(-1)?.close ?? null,
      startReplay: () => {
        const n = bars.length;
        if (n < 30) return;
        setReplay({ active: true, playing: false, speed: 2, cursor: Math.max(20, n - 150) });
      },
    };
    cellApis.set(index, api);
    return () => {
      cellApis.delete(index);
    };
  }, [index, tf, applyRange, applyDate, lastTick, bars.length, setCell]);

  // ------------------------------------------------------------------ legend
  const hi = hover != null && hover >= 0 && hover < display.length ? hover : display.length - 1;
  const hb = display[hi];
  const pb = display[hi - 1];
  const chg = hb && pb ? hb.close - pb.close : null;
  const chgPct = chg != null && pb ? (chg / pb.close) * 100 : null;
  const err = q.error as Error | null;
  const updateIndicator = (uid: string, patch: Partial<{ visible: boolean }>) =>
    setCell(index, { indicators: cell.indicators.map((i) => (i.uid === uid ? { ...i, ...patch } : i)) });
  const removeIndicator = (uid: string) => setCell(index, { indicators: cell.indicators.filter((i) => i.uid !== uid) });

  const editDrawing = drawings.find((d) => d.id === editing) ?? null;
  return (
    <div
      className={cn("relative flex h-full min-h-0 flex-col overflow-hidden bg-card", active ? "ring-1 ring-inset ring-primary/60" : "")}
      onMouseDown={() => !active && setActive(index)}
      data-testid={`chart-cell-${index}`}
    >
      <div ref={containerRef} className="relative min-h-0 flex-1" aria-label={`${cell.symbol} ${tfLabel(cell.tf)} chart`} role="img" />

      {/* legend */}
      <div className="pointer-events-none absolute left-2 top-1.5 z-10 flex max-w-[calc(100%-90px)] flex-col gap-0.5 text-[11px] leading-4">
        <div className="flex flex-wrap items-center gap-x-2">
          <span className="font-semibold text-foreground">{shortSymbol(cell.symbol)}</span>
          <span className="text-muted-foreground">
            {tfLabel(cell.tf)} · {exchange}
          </span>
          {source && (
            <span className={cn("rounded px-1 text-[10px] font-medium", source.live ? "bg-profit/15 text-profit" : "bg-warning/15 text-warning")}>{source.live ? "LIVE" : "SIMULATED"}</span>
          )}
          {replay.active && <span className="rounded bg-info/15 px-1 text-[10px] font-medium text-info">REPLAY</span>}
          {hb && (
            <span className="num flex flex-wrap gap-x-1.5 text-muted-foreground">
              <span>
                O <b className={cn(hb.close >= hb.open ? "text-profit" : "text-loss")}>{fmtPrice(hb.open)}</b>
              </span>
              <span>
                H <b className={cn(hb.close >= hb.open ? "text-profit" : "text-loss")}>{fmtPrice(hb.high)}</b>
              </span>
              <span>
                L <b className={cn(hb.close >= hb.open ? "text-profit" : "text-loss")}>{fmtPrice(hb.low)}</b>
              </span>
              <span>
                C <b className={cn(hb.close >= hb.open ? "text-profit" : "text-loss")}>{fmtPrice(hb.close)}</b>
              </span>
              {chg != null && (
                <b className={cn(chg >= 0 ? "text-profit" : "text-loss")}>
                  {chg >= 0 ? "+" : ""}
                  {fmtPrice(chg)} ({chgPct! >= 0 ? "+" : ""}
                  {chgPct!.toFixed(2)}%)
                </b>
              )}
              {hb.volume > 0 && <span>Vol {fmtVolume(hb.volume)}</span>}
            </span>
          )}
        </div>
        {cell.compare.map((s, k) => (
          <div key={s} className="pointer-events-auto flex items-center gap-1.5 self-start">
            <span className="h-2 w-2 rounded-full" style={{ background: COMPARE_COLORS[k % COMPARE_COLORS.length] }} />
            <span className="text-muted-foreground">{shortSymbol(s)}</span>
            <button className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={`Remove ${s} comparison`} onClick={() => setCell(index, { compare: cell.compare.filter((x) => x !== s) })}>
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        {!compact && cell.indicators.length > 4 && (
          <button className="pointer-events-auto self-start rounded px-1 text-[10px] text-muted-foreground hover:bg-muted" onClick={() => setLegendOpen((o) => !o)} aria-expanded={legendOpen}>
            {legendOpen ? "▾ hide indicator values" : `▸ ${cell.indicators.length} indicators`}
          </button>
        )}
        {!compact &&
          (legendOpen || cell.indicators.length <= 4) &&
          cell.indicators.map((ind) => {
            const def = INDICATOR_BY_ID[ind.id];
            if (!def) return null;
            const out = outputs[ind.uid];
            return (
              <div key={ind.uid} className="group pointer-events-auto flex items-center gap-1.5 self-start rounded px-0.5 hover:bg-card/80">
                <span className={cn("text-muted-foreground", !ind.visible && "line-through opacity-60")}>{indicatorLabel(def, ind.params)}</span>
                {ind.visible && !hasVolume && def.category === "Volume" && <span className="text-muted-foreground/70">n/a (no volume)</span>}
                {ind.visible &&
                  out &&
                  def.plots.map((p) => {
                    const v = out[p.key]?.[hi];
                    return v == null ? null : (
                      <span key={p.key} className="num" style={{ color: p.color }}>
                        {def.id === "VOL" && p.key === "vol" ? fmtVolume(v) : fmtPrice(v)}
                      </span>
                    );
                  })}
                <span className="hidden items-center gap-0.5 group-hover:flex">
                  <button className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={ind.visible ? `Hide ${def.short}` : `Show ${def.short}`} onClick={() => updateIndicator(ind.uid, { visible: !ind.visible })}>
                    {ind.visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                  </button>
                  <button className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={`${def.short} settings`} onClick={() => window.dispatchEvent(new CustomEvent("chart:edit-indicator", { detail: { index, uid: ind.uid } }))}>
                    <Settings2 className="h-3 w-3" />
                  </button>
                  <button className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={`Remove ${def.short}`} onClick={() => removeIndicator(ind.uid)}>
                    <X className="h-3 w-3" />
                  </button>
                </span>
              </div>
            );
          })}
      </div>

      {/* state overlays */}
      {q.isLoading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-card/60" role="status">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="sr-only">Loading chart…</span>
        </div>
      )}
      {err && !q.isLoading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-card/80 p-4" role="alert">
          <div className="max-w-sm text-center text-xs">
            <AlertTriangle className="mx-auto mb-2 h-5 w-5 text-loss" />
            <p className="font-medium">Could not load {shortSymbol(cell.symbol)}</p>
            <p className="mt-1 text-muted-foreground">{err.message}</p>
            <button className="mt-3 inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted" onClick={() => void q.refetch()}>
              <RotateCcw className="h-3 w-3" /> Retry
            </button>
          </div>
        </div>
      )}
      {!q.isLoading && !err && q.data && display.length === 0 && (
        <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-muted-foreground">No bars for this timeframe yet.</div>
      )}
      {q.isFetchingNextPage && (
        <div className="absolute bottom-10 left-2 z-10 flex items-center gap-1 rounded bg-card/90 px-2 py-1 text-[10px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> loading history…
        </div>
      )}

      {/* replay controls */}
      {replay.active && (
        <div className="absolute bottom-9 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1 rounded-lg border bg-popover px-2 py-1 text-xs shadow-lg" role="toolbar" aria-label="Bar replay">
          <button className="rounded p-1 hover:bg-muted" aria-label="Step back" onClick={() => setReplay((r) => ({ ...r, playing: false, cursor: Math.max(20, r.cursor - 1) }))}>
            <SkipBack className="h-3.5 w-3.5" />
          </button>
          <button className="rounded p-1 hover:bg-muted" aria-label={replay.playing ? "Pause" : "Play"} onClick={() => setReplay((r) => ({ ...r, playing: !r.playing }))}>
            {replay.playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </button>
          <button className="rounded p-1 hover:bg-muted" aria-label="Step forward" onClick={() => setReplay((r) => ({ ...r, playing: false, cursor: Math.min(bars.length, r.cursor + 1) }))}>
            <SkipForward className="h-3.5 w-3.5" />
          </button>
          <select className="rounded bg-transparent px-1 text-xs" aria-label="Replay speed" value={replay.speed} onChange={(e) => setReplay((r) => ({ ...r, speed: Number(e.target.value) }))}>
            {[1, 2, 5, 10, 20].map((s) => (
              <option key={s} value={s}>
                {s} bar/s
              </option>
            ))}
          </select>
          <input type="range" aria-label="Replay position" min={20} max={bars.length} value={replay.cursor} onChange={(e) => setReplay((r) => ({ ...r, playing: false, cursor: Number(e.target.value) }))} className="w-28 accent-primary" />
          <span className="num w-20 text-right text-muted-foreground">
            {replay.cursor}/{bars.length}
          </span>
          <button className="ml-1 rounded px-1.5 py-0.5 text-loss hover:bg-loss/10" onClick={() => setReplay({ active: false, playing: false, cursor: 0, speed: 2 })}>
            Exit
          </button>
        </div>
      )}

      {/* text entry for the text tool */}
      {textEdit && (
        <form
          className="absolute left-1/2 top-12 z-30 flex -translate-x-1/2 items-center gap-1 rounded-lg border bg-popover p-1.5 shadow-lg"
          onSubmit={(e) => {
            e.preventDefault();
            const list = useTerminal.getState().layout.drawings[cell.symbol] ?? [];
            setDrawings(cell.symbol, textEdit.text.trim() ? list.map((d) => (d.id === textEdit.id ? { ...d, text: textEdit.text.trim() } : d)) : list.filter((d) => d.id !== textEdit.id));
            setTextEdit(null);
          }}
        >
          <input autoFocus className="h-7 w-56 rounded border bg-background px-2 text-xs" placeholder="Text…" value={textEdit.text} onChange={(e) => setTextEdit({ ...textEdit, text: e.target.value })} aria-label="Drawing text" />
          <button className="h-7 rounded bg-primary px-2 text-xs text-primary-foreground">Add</button>
        </form>
      )}

      {/* drawing properties */}
      {editDrawing && (
        <div className="absolute right-16 top-10 z-30 w-60 rounded-lg border bg-popover p-3 text-xs shadow-lg" role="dialog" aria-label="Drawing properties">
          <div className="mb-2 flex items-center justify-between font-medium">
            Drawing
            <button aria-label="Close" className="rounded p-0.5 hover:bg-muted" onClick={() => setEditing(null)}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {["#2962ff", "#f23645", "#089981", "#ff9800", "#9c27b0", "#00bcd4", "#787b86", "#ffffff"].map((c) => (
              <button
                key={c}
                aria-label={`Colour ${c}`}
                className={cn("h-5 w-5 rounded-full border", editDrawing.color === c && "ring-2 ring-primary ring-offset-1 ring-offset-popover")}
                style={{ background: c }}
                onClick={() => setDrawings(cell.symbol, drawings.map((d) => (d.id === editDrawing.id ? { ...d, color: c } : d)))}
              />
            ))}
          </div>
          <label className="mb-2 flex items-center justify-between gap-2">
            Width
            <input type="range" min={1} max={4} value={editDrawing.width} onChange={(e) => setDrawings(cell.symbol, drawings.map((d) => (d.id === editDrawing.id ? { ...d, width: Number(e.target.value) } : d)))} className="w-28 accent-primary" />
          </label>
          <label className="mb-2 flex flex-col gap-1">
            Text
            <input className="h-7 rounded border bg-background px-2" value={editDrawing.text ?? ""} onChange={(e) => setDrawings(cell.symbol, drawings.map((d) => (d.id === editDrawing.id ? { ...d, text: e.target.value } : d)), false)} />
          </label>
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={!!editDrawing.locked} onChange={(e) => setDrawings(cell.symbol, drawings.map((d) => (d.id === editDrawing.id ? { ...d, locked: e.target.checked } : d)))} /> Lock
            </label>
            <button
              className="rounded px-2 py-1 text-loss hover:bg-loss/10"
              onClick={() => {
                setDrawings(cell.symbol, drawings.filter((d) => d.id !== editDrawing.id));
                setEditing(null);
                select(null);
              }}
            >
              Delete
            </button>
          </div>
        </div>
      )}
      <span className="sr-only">{lastTick ? `Last price ${fmtPrice(lastTick.ltp)}` : ""}</span>
    </div>
  );
}
