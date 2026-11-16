"use client";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { realtime, type Frame, type Spec } from "@/lib/ws";

export interface TickData {
  symbol: string;
  ts: string;
  ltp: number;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  oi?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  bid?: number | null;
  ask?: number | null;
}

function client() {
  return realtime(() => useAuth.getState().token);
}

/** Subscribe to any realtime channel for the component's lifetime. */
export function useRealtime(spec: Spec | null, handler: (f: Frame) => void): void {
  const ref = useRef(handler);
  ref.current = handler;
  const key = spec ? JSON.stringify(spec) : null;
  useEffect(() => {
    if (!key) return;
    const s = JSON.parse(key) as Spec;
    return client().subscribe(s, (f) => ref.current(f));
  }, [key]);
}

/** Live ticks for a set of symbols, batched to one render per animation frame. */
export function useTicks(symbols: string[]): Record<string, TickData> {
  const [ticks, setTicks] = useState<Record<string, TickData>>({});
  const pending = useRef<Record<string, TickData>>({});
  const raf = useRef<number | null>(null);
  const key = [...new Set(symbols)].sort().join(",");

  useEffect(() => {
    if (!key) return;
    const unsub = client().subscribe({ channel: "ticks", symbols: key.split(",") }, (f) => {
      const t = f.data as TickData;
      pending.current[t.symbol] = t;
      if (raf.current === null) {
        raf.current = requestAnimationFrame(() => {
          raf.current = null;
          const batch = pending.current;
          pending.current = {};
          setTicks((prev) => ({ ...prev, ...batch }));
        });
      }
    });
    return () => {
      unsub();
      if (raf.current !== null) cancelAnimationFrame(raf.current);
      raf.current = null;
    };
  }, [key]);
  return ticks;
}
