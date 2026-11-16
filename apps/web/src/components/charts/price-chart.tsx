"use client";
/**
 * TradingView lightweight-charts wrapper: candles + volume + optional line
 * overlays, markers and live last-price updates. Theme aware.
 */
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useTheme } from "next-themes";
import * as React from "react";
import { chartPalette, cssHsl } from "./theme";

export interface CandlePoint {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Overlay {
  id: string;
  color: string;
  points: { ts: string; value: number | null }[];
  pane?: number;
  width?: number;
  dashed?: boolean;
}

export interface Marker {
  ts: string;
  position: "aboveBar" | "belowBar";
  color?: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text?: string;
}

const IST_OFFSET = 5.5 * 3600;
const toTime = (iso: string) => (Math.floor(new Date(iso).getTime() / 1000) + IST_OFFSET) as UTCTimestamp;

export function PriceChart({
  candles,
  overlays = [],
  markers = [],
  height = 420,
  live,
  showVolume = true,
  line = false,
}: {
  candles: CandlePoint[];
  overlays?: Overlay[];
  markers?: Marker[];
  height?: number;
  live?: number | null;
  showVolume?: boolean;
  line?: boolean;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const chartRef = React.useRef<IChartApi | null>(null);
  const mainRef = React.useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>(null);
  const lastRef = React.useRef<CandlePoint | null>(null);
  const { resolvedTheme } = useTheme();

  React.useEffect(() => {
    if (!ref.current) return;
    const p = chartPalette();
    const chart = createChart(ref.current, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: p.text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;
    const main = line
      ? chart.addSeries(LineSeries, { color: p.primary, lineWidth: 2 })
      : chart.addSeries(CandlestickSeries, {
          upColor: p.profit,
          downColor: p.loss,
          borderVisible: false,
          wickUpColor: p.profit,
          wickDownColor: p.loss,
        });
    mainRef.current = main;
    const data = candles.map((c) => ({ time: toTime(c.ts), open: c.open, high: c.high, low: c.low, close: c.close }));
    if (line) (main as ISeriesApi<"Line">).setData(data.map((d) => ({ time: d.time, value: d.close })));
    else (main as ISeriesApi<"Candlestick">).setData(data);
    lastRef.current = candles[candles.length - 1] ?? null;

    if (showVolume && candles.some((c) => (c.volume ?? 0) > 0)) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(
        candles.map((c) => ({
          time: toTime(c.ts),
          value: c.volume ?? 0,
          color: c.close >= c.open ? cssHsl("profit", 0.35) : cssHsl("loss", 0.35),
        })),
      );
    }
    for (const o of overlays) {
      const s = chart.addSeries(
        LineSeries,
        { color: o.color, lineWidth: (o.width ?? 1) as 1 | 2 | 3 | 4, lineStyle: o.dashed ? 2 : 0, priceLineVisible: false, lastValueVisible: false },
        o.pane ?? 0,
      );
      s.setData(o.points.filter((pt) => pt.value !== null && Number.isFinite(pt.value)).map((pt) => ({ time: toTime(pt.ts), value: pt.value as number })));
    }
    if (markers.length) {
      createSeriesMarkers(
        main,
        markers
          .map((m) => ({ time: toTime(m.ts) as Time, position: m.position, color: m.color ?? (m.position === "belowBar" ? p.profit : p.loss), shape: m.shape, text: m.text }))
          .sort((a, b) => (a.time as number) - (b.time as number)) as SeriesMarker<Time>[],
      );
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
      mainRef.current = null;
    };
  }, [candles, overlays, markers, height, resolvedTheme, showVolume, line]);

  // live last-price update without re-creating the chart
  React.useEffect(() => {
    const s = mainRef.current;
    const last = lastRef.current;
    if (!s || !last || live === null || live === undefined) return;
    const t = toTime(last.ts);
    if (line) (s as ISeriesApi<"Line">).update({ time: t, value: live });
    else (s as ISeriesApi<"Candlestick">).update({ time: t, open: last.open, high: Math.max(last.high, live), low: Math.min(last.low, live), close: live });
  }, [live, line]);

  return <div ref={ref} style={{ height }} className="w-full" role="img" aria-label="Price chart" />;
}
