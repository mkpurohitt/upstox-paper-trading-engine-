"use client";
/**
 * Backend reachability banner. When the web app cannot reach the API (backend not started, wrong port, a proxy
 * error), every screen would otherwise fail with generic errors; this tells the user exactly what is wrong and
 * re-checks until the API is back.
 */
import { AlertTriangle, RefreshCw } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

type State = "unknown" | "ok" | "down" | "degraded";

async function probe(): Promise<State> {
  try {
    const res = await fetch("/api/health", { cache: "no-store", credentials: "omit" });
    const isJson = (res.headers.get("content-type") || "").includes("application/json");
    if (!isJson) return "down"; // the Next.js proxy answered, not the API
    const body = (await res.json()) as { status?: string; db?: boolean };
    return res.ok && body.status === "ok" ? "ok" : body.db === false ? "degraded" : "ok";
  } catch {
    return "down";
  }
}

export function useApiStatus(): { state: State; recheck: () => void } {
  const [state, setState] = React.useState<State>("unknown");
  const stateRef = React.useRef<State>("unknown");
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      const s = await probe();
      if (!alive) return;
      stateRef.current = s;
      setState(s);
      timer = setTimeout(run, s === "ok" ? 30_000 : 4_000);
    };
    void run();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [tick]);
  return { state, recheck: () => setTick((t) => t + 1) };
}

export function ApiStatusBanner({ className }: { className?: string }) {
  const { state, recheck } = useApiStatus();
  if (state !== "down" && state !== "degraded") return null;
  return (
    <div role="alert" className={cn("flex items-start gap-2.5 border-b border-loss/30 bg-loss/10 px-4 py-2.5 text-xs text-foreground", className)}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-loss" />
      <div className="min-w-0 flex-1 leading-relaxed">
        {state === "down" ? (
          <>
            <span className="font-medium">Can&apos;t reach the AlgoDesk API.</span> Start the backend (from the project folder run{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-2xs">uv run python scripts/dev.py</code>) and keep that terminal
            open. This page reconnects automatically.
          </>
        ) : (
          <>
            <span className="font-medium">The API is running but its database is unavailable.</span> Check <code className="rounded bg-muted px-1 py-0.5 font-mono text-2xs">DATABASE_URL</code>{" "}
            in <code className="rounded bg-muted px-1 py-0.5 font-mono text-2xs">.env</code> (leave the SQLite default unless Postgres is running).
          </>
        )}
      </div>
      <button onClick={recheck} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium text-loss hover:bg-loss/10" aria-label="Check the API again">
        <RefreshCw className="h-3 w-3" /> Retry
      </button>
    </div>
  );
}
