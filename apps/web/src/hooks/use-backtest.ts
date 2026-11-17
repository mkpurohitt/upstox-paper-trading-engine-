"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { api, unwrap } from "@/lib/api";
import { useRealtime } from "./use-realtime";

export interface Progress {
  status: string;
  progress: number;
  message?: string;
}

/** Fetch a backtest and keep it fresh while running (WS progress + polling fallback). */
export function useBacktest(id: number | null) {
  const qc = useQueryClient();
  const [live, setLive] = React.useState<Progress | null>(null);
  const q = useQuery({
    queryKey: ["backtest", id],
    queryFn: () => unwrap(api.GET("/api/backtests/{backtest_id}", { params: { path: { backtest_id: id! } } })),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data && ["queued", "running"].includes(query.state.data.status) ? 2500 : false),
  });
  useRealtime(id !== null && q.data && ["queued", "running"].includes(q.data.status) ? { channel: "backtest", id } : null, (f) => {
    const d = f.data as Progress;
    setLive(d);
    if (d.status === "completed" || d.status === "failed") {
      void qc.invalidateQueries({ queryKey: ["backtest", id] });
      void qc.invalidateQueries({ queryKey: ["backtests"] });
      void qc.invalidateQueries({ queryKey: ["strategies"] });
    }
  });
  React.useEffect(() => setLive(null), [id]);
  const progress = live && q.data && ["queued", "running"].includes(q.data.status) ? live : q.data ? { status: q.data.status, progress: q.data.progress } : null;
  return { ...q, progress };
}
