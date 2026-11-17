"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Braces, CheckCircle2, ExternalLink, FlaskConical, Hammer, Rocket, ShieldAlert, TriangleAlert } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { PayoffChart } from "@/components/charts/payoff-chart";
import { Sparkline } from "@/components/charts/sparkline";
import { SERIES } from "@/components/charts/theme";
import { Pnl } from "@/components/common";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox, Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { useTicks } from "@/hooks/use-realtime";
import { api, ApiError, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Card } from "@/lib/copilot";
import { compactNum, croreInr, inr, num, pct, shortDate, timeAgo } from "@/lib/format";
import { sendDraftToBuilder } from "@/lib/options-draft";
import { cn, pnlClass } from "@/lib/utils";

const PriceChart = dynamic(() => import("@/components/charts/price-chart").then((m) => m.PriceChart), {
  ssr: false,
  loading: () => <Skeleton className="h-[220px]" />,
});

type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const short = (s: unknown) => String(s ?? "").split(":").pop() ?? "";

function Shell({ title, icon, actions, children, className }: { title: React.ReactNode; icon?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-lg border bg-card/60", className)}>
      <div className="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2 text-xs font-semibold">
          {icon}
          <span className="truncate">{title}</span>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

function Mini({ label, value, tone, hint }: { label: string; value: React.ReactNode; tone?: "profit" | "loss" | "warning"; hint?: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-md bg-muted/40 px-2 py-1.5">
      <div className="truncate text-2xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("num truncate text-sm font-semibold", tone === "profit" && "text-profit", tone === "loss" && "text-loss", tone === "warning" && "text-warning")}>{value}</div>
      {hint ? <div className="truncate text-2xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function OpenLink({ href, children = "Open" }: { href: string; children?: React.ReactNode }) {
  return (
    <Button asChild size="xs" variant="ghost" className="text-muted-foreground">
      <Link href={href}>
        {children} <ArrowUpRight className="h-3 w-3" />
      </Link>
    </Button>
  );
}

// ---------------------------------------------------------------- market data

function QuotesCard({ c }: { c: Any }) {
  const quotes = (c.quotes ?? []) as Any[];
  const ticks = useTicks(quotes.map((q) => q.symbol as string));
  return (
    <Shell title={`Quotes · ${quotes.length}`} actions={<span className="flex items-center gap-1 text-2xs text-muted-foreground"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit" /> live</span>}>
      <div className="grid gap-2 sm:grid-cols-2">
        {quotes.map((q) => {
          const t = ticks[q.symbol];
          const ltp = t?.ltp ?? q.ltp;
          const chg = t?.change_pct ?? q.change_pct;
          const lo = q.week52_low ?? q.low;
          const hi = q.week52_high ?? q.high;
          const pos = lo && hi && hi > lo ? Math.min(100, Math.max(0, ((ltp - lo) / (hi - lo)) * 100)) : null;
          return (
            <Link key={q.symbol} href={`/analysis/technical?symbol=${encodeURIComponent(q.symbol)}`} className="rounded-md border p-2 transition-colors hover:bg-accent">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm font-semibold">{short(q.symbol)}</span>
                <span className={cn("num text-xs", pnlClass(chg))}>{pct(chg)}</span>
              </div>
              <div className="num text-lg font-semibold">{inr(ltp)}</div>
              <div className="truncate text-2xs text-muted-foreground">
                O {num(q.open)} · H {num(q.high)} · L {num(q.low)} · Vol {compactNum(q.volume)}
              </div>
              {pos !== null && (
                <div className="mt-1.5" title="Position within 52-week range">
                  <div className="relative h-1 rounded-full bg-muted">
                    <span className="absolute -top-0.5 h-2 w-0.5 rounded bg-primary" style={{ left: `${pos}%` }} />
                  </div>
                  <div className="mt-0.5 flex justify-between text-2xs text-muted-foreground">
                    <span>52W L {num(lo, 0)}</span>
                    <span>52W H {num(hi, 0)}</span>
                  </div>
                </div>
              )}
            </Link>
          );
        })}
      </div>
    </Shell>
  );
}

function ChartCard({ c }: { c: Any }) {
  const overlays = React.useMemo(
    () =>
      Object.entries((c.overlays ?? {}) as Record<string, { ts: string; value: number | null }[]>).map(([id, points], i) => ({
        id,
        color: SERIES[i % SERIES.length]!,
        points,
      })),
    [c.overlays],
  );
  const s = (c.summary ?? {}) as Any;
  const trend = String(s.trend ?? "");
  return (
    <Shell
      title={`${short(c.symbol)} · ${c.interval}`}
      icon={<Badge variant={trend.includes("bull") ? "profit" : trend.includes("bear") ? "loss" : "secondary"}>{trend || "—"}</Badge>}
      actions={<OpenLink href={`/analysis/technical?symbol=${encodeURIComponent(String(c.symbol))}`}>Full chart</OpenLink>}
    >
      <PriceChart candles={c.candles ?? []} overlays={overlays} height={220} showVolume={false} />
      <div className="mt-2 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <Mini label="Close" value={num(s.close)} />
        <Mini label="EMA 20" value={num(s.ema20)} />
        <Mini label="EMA 50" value={num(s.ema50)} />
        <Mini label="RSI" value={num(s.rsi, 0)} tone={s.rsi > 70 ? "warning" : s.rsi < 30 ? "warning" : undefined} />
        <Mini label="ADX" value={num(s.adx, 0)} />
        <Mini label="Supertrend" value={s.supertrend ?? "—"} tone={s.supertrend === "up" ? "profit" : "loss"} />
      </div>
    </Shell>
  );
}

function OptionChainCard({ c }: { c: Any }) {
  const a = (c.analytics ?? {}) as Any;
  const rows = (c.strikes ?? []) as Any[];
  const maxOi = Math.max(1, ...rows.flatMap((r) => [r.call_oi ?? 0, r.put_oi ?? 0]));
  return (
    <Shell title={`${c.underlying} option chain · ${shortDate(String(c.expiry))}`} actions={<OpenLink href="/analysis/option-chain">Full chain</OpenLink>}>
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <Mini label="Spot" value={num(c.spot)} />
        <Mini label="PCR" value={num(c.pcr, 2)} tone={c.pcr > 1 ? "profit" : "loss"} />
        <Mini label="Max pain" value={num(c.max_pain, 0)} />
        <Mini label="ATM IV" value={a.atm_iv ? `${num(a.atm_iv, 1)}%` : "—"} />
        <Mini label="Straddle" value={num(a.atm_straddle)} />
        <Mini label="±1σ range" value={a.expected_range ? `${num(a.expected_range[0], 0)}–${num(a.expected_range[1], 0)}` : "—"} />
      </div>
      <table className="num mt-2 w-full text-2xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 text-right font-medium">Call OI</th>
            <th className="text-right font-medium">LTP</th>
            <th className="text-center font-medium">Strike</th>
            <th className="text-left font-medium">LTP</th>
            <th className="text-left font-medium">Put OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.strike} className={cn("border-t", r.strike === c.atm_strike && "bg-primary/10 font-semibold")}>
              <td className="relative py-0.5 text-right">
                <span className="absolute inset-y-0.5 right-0 rounded-sm bg-loss/15" style={{ width: `${((r.call_oi ?? 0) / maxOi) * 100}%` }} />
                <span className="relative">{compactNum(r.call_oi)}</span>
              </td>
              <td className="text-right">{num(r.call_ltp)}</td>
              <td className="text-center">{num(r.strike, 0)}</td>
              <td>{num(r.put_ltp)}</td>
              <td className="relative">
                <span className="absolute inset-y-0.5 left-0 rounded-sm bg-profit/15" style={{ width: `${((r.put_oi ?? 0) / maxOi) * 100}%` }} />
                <span className="relative">{compactNum(r.put_oi)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-2xs text-muted-foreground">
        Resistance (call OI): {(a.resistance ?? []).join(", ") || "—"} · Support (put OI): {(a.support ?? []).join(", ") || "—"}
      </p>
    </Shell>
  );
}

function PayoffCard({ c }: { c: Any }) {
  const g = (c.greeks ?? {}) as Any;
  return (
    <Shell
      title={`${String(c.structure ?? "custom").replace(/_/g, " ")} · ${c.underlying} ${shortDate(String(c.expiry))}`}
      actions={<OpenLink href="/analysis/options-builder">Options builder</OpenLink>}
    >
      <div className="mb-2 flex flex-wrap gap-1">
        {((c.legs ?? []) as Any[]).map((l, i) => (
          <Badge key={i} variant={l.action === "BUY" ? "profit" : "loss"}>
            {l.action === "BUY" ? "+" : "−"}
            {l.lots} {num(l.strike, 0)} {l.option_type} @ {num(l.premium)}
          </Badge>
        ))}
      </div>
      <PayoffChart points={c.points ?? []} spot={c.spot} breakevens={c.breakevens ?? []} height={200} />
      <div className="mt-2 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <Mini label="Net premium" value={inr(c.net_premium, { decimals: 0 })} tone={c.net_premium >= 0 ? "profit" : "loss"} />
        <Mini label="Max profit" value={c.max_profit == null ? "Unlimited" : inr(c.max_profit, { decimals: 0 })} tone="profit" />
        <Mini label="Max loss" value={c.max_loss == null ? "Unlimited" : inr(c.max_loss, { decimals: 0 })} tone="loss" />
        <Mini label="POP" value={c.pop != null ? `${num(c.pop * 100, 0)}%` : "—"} />
        <Mini label="Θ / day" value={num(g.theta, 0)} tone={g.theta >= 0 ? "profit" : "loss"} />
        <Mini label="Vega" value={num(g.vega, 0)} hint={`Δ ${num(g.delta, 2)}`} />
      </div>
    </Shell>
  );
}

function FundamentalsCard({ c }: { c: Any }) {
  const r = (c.ratios ?? {}) as Any;
  const sh = (c.shareholding ?? {}) as Any;
  const parts = [
    ["Promoter", sh.promoter, SERIES[0]],
    ["FII", sh.fii, SERIES[1]],
    ["DII", sh.dii, SERIES[2]],
    ["Public", sh.public, SERIES[3]],
  ] as const;
  return (
    <Shell
      title={`${c.name} · ${c.sector}`}
      icon={c.source === "mock" ? <Badge variant="warning">sample</Badge> : null}
      actions={<OpenLink href={`/analysis/fundamental?symbol=${encodeURIComponent(String(c.symbol))}`}>Details</OpenLink>}
    >
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <Mini label="M-cap" value={croreInr(r.market_cap_cr)} />
        <Mini label="P/E" value={num(r.pe, 1)} />
        <Mini label="P/B" value={num(r.pb, 2)} />
        <Mini label="ROE" value={`${num(r.roe_pct, 1)}%`} />
        <Mini label="D/E" value={num(r.debt_to_equity, 2)} />
        <Mini label="Div yield" value={`${num(r.dividend_yield_pct, 2)}%`} />
      </div>
      {sh.promoter != null && (
        <div className="mt-2">
          <div className="flex h-2 overflow-hidden rounded-full" role="img" aria-label="Shareholding">
            {parts.map(([k, v, col]) => (
              <span key={k} style={{ width: `${v}%`, background: col }} />
            ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-2xs text-muted-foreground">
            {parts.map(([k, v, col]) => (
              <span key={k} className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm" style={{ background: col }} /> {k} {num(v, 1)}%
              </span>
            ))}
          </div>
        </div>
      )}
      {(c.annual ?? []).length > 0 && (
        <div className="mt-2 flex gap-2 overflow-x-auto text-2xs scrollbar-thin">
          {((c.annual ?? []) as Any[]).map((y) => (
            <div key={y.fy} className="shrink-0 rounded-md bg-muted/40 px-2 py-1">
              <div className="font-medium">{y.fy}</div>
              <div className="num text-muted-foreground">Rev ₹{compactNum(y.revenue_cr)}Cr · PAT ₹{compactNum(y.pat_cr)}Cr</div>
            </div>
          ))}
        </div>
      )}
    </Shell>
  );
}

function NewsCard({ c }: { c: Any }) {
  const items = (c.items ?? []) as Any[];
  return (
    <Shell title="Headlines" icon={c.source === "sample" ? <Badge variant="warning">sample</Badge> : null} actions={<OpenLink href="/news">News</OpenLink>}>
      <ul className="flex flex-col divide-y">
        {items.slice(0, 8).map((n, i) => {
          const real = typeof n.url === "string" && !n.url.includes(".invalid");
          return (
            <li key={i} className="flex items-start gap-2 py-1.5">
              <Badge variant={n.sentiment === "positive" ? "profit" : n.sentiment === "negative" ? "loss" : "secondary"} className="mt-0.5 shrink-0 capitalize">
                {n.sentiment}
              </Badge>
              <div className="min-w-0 text-xs">
                {real ? (
                  <a href={n.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-primary">
                    {n.title} <ExternalLink className="inline h-3 w-3" />
                  </a>
                ) : (
                  <span className="font-medium">{n.title}</span>
                )}
                <div className="text-2xs text-muted-foreground">
                  {n.source} · {n.published_at ? timeAgo(n.published_at) : ""} {(n.tickers ?? []).slice(0, 3).map(short).join(" ")}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </Shell>
  );
}

function fmtCell(v: unknown, key: string): React.ReactNode {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (key.endsWith("_pct") || key === "change_pct") return <span className={key.includes("change") || key.startsWith("ret") ? pnlClass(v) : ""}>{num(v, 2)}%</span>;
    if (key.includes("market_cap")) return compactNum(v);
    if (Math.abs(v) >= 1e5) return compactNum(v);
    return num(v, Number.isInteger(v) ? 0 : 2);
  }
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return JSON.stringify(v).slice(0, 60);
  const s = String(v);
  return s.includes(":") && s.length < 30 ? short(s) : s;
}

function TableCard({ c }: { c: Any }) {
  const rows = (c.rows ?? []) as Any[];
  const [all, setAll] = React.useState(false);
  const cols = ((c.columns as string[] | undefined) ?? Object.keys(rows[0] ?? {})).slice(0, 8);
  const shown = all ? rows : rows.slice(0, 8);
  return (
    <Shell title={String(c.title ?? "Results")} actions={c.link ? <OpenLink href={String(c.link)} /> : null}>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No rows.</p>
      ) : (
        <div className="overflow-x-auto scrollbar-thin">
          <table className="num w-full text-2xs">
            <thead className="text-muted-foreground">
              <tr>
                {cols.map((k) => (
                  <th key={k} className="whitespace-nowrap px-1.5 py-1 text-left text-[10px] font-medium uppercase tracking-wide">
                    {k.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i} className="border-t">
                  {cols.map((k) => (
                    <td key={k} className="whitespace-nowrap px-1.5 py-1">
                      {fmtCell(r[k], k)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 8 && (
        <Button size="xs" variant="ghost" className="mt-1" onClick={() => setAll(!all)}>
          {all ? "Show less" : `Show all ${rows.length}`}
        </Button>
      )}
    </Shell>
  );
}

function KvCard({ c }: { c: Any }) {
  const data = (c.data ?? {}) as Any;
  return (
    <Shell title={String(c.title ?? "Details")}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        {Object.entries(data)
          .filter(([, v]) => typeof v !== "object" || v === null)
          .slice(0, 18)
          .map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="truncate text-2xs capitalize text-muted-foreground">{k.replace(/_/g, " ")}</dt>
              <dd className="num truncate font-medium">{fmtCell(v, k)}</dd>
            </div>
          ))}
      </dl>
    </Shell>
  );
}

function ScreenerCard({ c }: { c: Any }) {
  const conds = ((c.conditions ?? []) as Any[]).map((x) => `${(c.fields?.[x.field]?.label as string) ?? x.field} ${x.op} ${x.value}`).join(" · ");
  return (
    <TableCard
      c={{
        title: `Screener · ${c.matched}/${c.scanned} in ${c.universe}${conds ? ` · ${conds}` : ""}`,
        columns: ["symbol", "sector", ...((c.columns as string[]) ?? []).filter((k) => k !== "market_cap_cr")],
        rows: c.rows,
        link: "/analysis/screener",
      }}
    />
  );
}

// ---------------------------------------------------------------- strategy

function StrategyCard({ c, onAsk }: { c: Any; onAsk?: (q: string) => void }) {
  const router = useRouter();
  const [json, setJson] = React.useState(false);
  const d = (c.dsl ?? {}) as Any;
  const where = d.kind === "options" ? d.universe?.underlying : d.kind === "pair" ? `${short(d.pair?.leg_a)} / ${short(d.pair?.leg_b)}` : ((d.universe?.symbols ?? []) as string[]).map(short).join(", ");
  return (
    <Shell
      title={d.name ?? "Strategy"}
      icon={c.valid ? <CheckCircle2 className="h-3.5 w-3.5 text-profit" /> : <TriangleAlert className="h-3.5 w-3.5 text-warning" />}
      actions={
        <Button size="xs" variant="ghost" onClick={() => setJson(!json)} aria-pressed={json}>
          <Braces className="h-3 w-3" /> DSL
        </Button>
      }
    >
      <div className="flex flex-wrap gap-1 text-2xs">
        <Badge variant="info">{d.kind}</Badge>
        <Badge variant="secondary">{d.timeframe}</Badge>
        <Badge variant="secondary">{d.product}</Badge>
        {where ? <Badge variant="outline">{where}</Badge> : null}
        {(d.legs ?? []).length ? <Badge variant="outline">{d.legs.length} legs</Badge> : null}
      </div>
      {c.explanation ? <p className="mt-2 text-xs text-muted-foreground">{String(c.explanation)}</p> : null}
      {(c.errors ?? []).length > 0 && (
        <ul className="mt-2 list-inside list-disc text-2xs text-warning">
          {((c.errors ?? []) as Any[]).slice(0, 5).map((e, i) => (
            <li key={i}>
              {(e.loc ?? []).join(".")}: {e.msg}
            </li>
          ))}
        </ul>
      )}
      {json && <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted/50 p-2 font-mono text-2xs scrollbar-thin">{JSON.stringify(d, null, 2)}</pre>}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => sendDraftToBuilder(d, router.push)}>
          <Hammer /> Send to Builder
        </Button>
        {onAsk && c.valid && (
          <Button size="sm" variant="outline" onClick={() => onAsk("Backtest this strategy over 1 year")}>
            <FlaskConical /> Backtest it
          </Button>
        )}
      </div>
    </Shell>
  );
}

function BacktestCard({ c, onAsk }: { c: Any; onAsk?: (q: string) => void }) {
  const router = useRouter();
  const m = (c.metrics ?? {}) as Any;
  const eq = ((c.equity ?? []) as Any[]).map((p) => Number(p.value));
  if (c.status !== "completed") {
    return (
      <Shell title={`Backtest #${c.backtest_id} · ${c.name ?? ""}`}>
        <p className="text-xs text-muted-foreground">Still running — results will appear on the Build page.</p>
      </Shell>
    );
  }
  return (
    <Shell title={`Backtest · ${c.name}`} icon={<Badge variant="secondary">{c.period}</Badge>}>
      <Sparkline values={eq} height={56} />
      <div className="mt-2 grid grid-cols-4 gap-1.5">
        <Mini label="Net P&L" value={<Pnl value={m.net_pnl} />} />
        <Mini label="Return" value={pct(m.total_return_pct)} tone={(m.total_return_pct ?? 0) >= 0 ? "profit" : "loss"} />
        <Mini label="CAGR" value={pct(m.cagr_pct)} />
        <Mini label="Sharpe" value={num(m.sharpe, 2)} />
        <Mini label="Max DD" value={pct(m.max_drawdown_pct, 2, false)} tone="loss" />
        <Mini label="Trades" value={m.trades ?? "—"} />
        <Mini label="Win rate" value={m.win_rate_pct != null ? `${num(m.win_rate_pct, 1)}%` : "—"} />
        <Mini label="Charges" value={inr(m.total_charges, { decimals: 0 })} />
      </div>
      {((c.warnings ?? []) as string[]).map((w, i) => (
        <p key={i} className="mt-1.5 flex items-start gap-1 text-2xs text-warning">
          <TriangleAlert className="mt-px h-3 w-3 shrink-0" /> {w}
        </p>
      ))}
      <div className="mt-2 flex flex-wrap gap-2">
        {c.strategy_id ? (
          <Button size="sm" variant="outline" asChild>
            <Link href={`/build/${c.strategy_id}`}>
              <Hammer /> Open strategy
            </Link>
          </Button>
        ) : c.dsl ? (
          <Button size="sm" variant="outline" onClick={() => sendDraftToBuilder(c.dsl, router.push)}>
            <Hammer /> Open in Builder
          </Button>
        ) : null}
        {onAsk && (
          <Button size="sm" variant="outline" onClick={() => onAsk("Deploy it in paper mode")}>
            <Rocket /> Paper-trade it
          </Button>
        )}
      </div>
    </Shell>
  );
}

function DeployConfirmCard({ c }: { c: Any }) {
  const user = useAuth((s) => s.user);
  const [state, setState] = React.useState<"idle" | "dismissed" | "deployed">("idle");
  const [ack, setAck] = React.useState(false);
  const [totp, setTotp] = React.useState("");
  const [conn, setConn] = React.useState<string | undefined>(undefined);
  const [depId, setDepId] = React.useState<number | null>(null);
  const live = c.mode === "live";
  const conns = useQuery({ queryKey: ["broker-connections"], queryFn: () => unwrap(api.GET("/api/brokers/connections")), enabled: live });
  const connected = (conns.data ?? []).filter((x) => x.status === "connected");
  React.useEffect(() => {
    if (!conn && connected[0]) setConn(String(connected[0].id));
  }, [connected, conn]);
  const deploy = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/deployments", {
          body: {
            strategy_id: Number(c.strategy_id),
            mode: c.mode,
            connection_id: live && conn ? Number(conn) : null,
            multiplier: Number(c.multiplier ?? 1),
            capital: Number(c.capital ?? 1_000_000),
            risk_limits: c.risk_limits,
            notify_channels: ["in_app"],
            totp_code: live ? totp : null,
            acknowledge_risk: ack,
          },
        }),
      ),
    onSuccess: (d) => {
      setState("deployed");
      setDepId(d.id);
      toast.success(`Deployed "${d.name}" (${d.mode})`);
    },
    onError: (e: Error) => toast.error(e instanceof ApiError ? e.message : "Deploy failed"),
  });
  const rl = (c.risk_limits ?? {}) as Any;
  if (state === "dismissed") return <p className="text-2xs text-muted-foreground">Deployment cancelled.</p>;
  return (
    <Shell
      title={`Confirm deployment · ${c.name}`}
      icon={<Rocket className="h-3.5 w-3.5 text-primary" />}
      className={cn(live ? "border-loss/40" : "border-primary/40")}
    >
      {state === "deployed" ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <CheckCircle2 className="h-4 w-4 text-profit" /> Deployment is running in {String(c.mode)} mode.
          <Button size="xs" variant="outline" asChild>
            <Link href={`/deployments?focus=${depId}`}>View on Live</Link>
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            <Mini label="Mode" value={<Badge variant={live ? "loss" : c.mode === "paper" ? "info" : "secondary"}>{String(c.mode).toUpperCase()}</Badge>} />
            <Mini label="Capital × mult." value={`${inr(c.capital, { compact: true })} × ${c.multiplier}`} />
            <Mini label="Max loss / day" value={inr(rl.max_loss_per_day, { decimals: 0 })} tone="loss" />
            <Mini label="Algo-ID" value={<span className="font-mono text-2xs">{String(c.algo_id_preview)}</span>} />
          </div>
          {live && (
            <div className="flex flex-col gap-2 rounded-md border border-loss/30 bg-loss/5 p-2 text-xs">
              {!user?.totp_enabled && (
                <p className="flex items-center gap-1 text-loss">
                  <ShieldAlert className="h-3.5 w-3.5" /> Live trading needs 2FA.{" "}
                  <Link href="/profile?tab=security" className="underline">
                    Enable it
                  </Link>
                </p>
              )}
              {connected.length === 0 ? (
                <p className="text-loss">
                  No connected broker.{" "}
                  <Link href="/profile?tab=brokers" className="underline">
                    Connect one
                  </Link>
                </p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label="Broker">
                    <Select value={conn} onValueChange={setConn} options={connected.map((x) => ({ value: String(x.id), label: `${x.display_name} · ${x.client_id}` }))} />
                  </Field>
                  <Field label="2FA code">
                    <Input inputMode="numeric" autoComplete="one-time-code" placeholder="123456" value={totp} onChange={(e) => setTotp(e.target.value)} />
                  </Field>
                </div>
              )}
            </div>
          )}
          <label className="flex items-start gap-2 text-2xs text-muted-foreground">
            <Checkbox checked={ack} onCheckedChange={(v) => setAck(v === true)} className="mt-0.5" />
            I understand the risks, that backtests don&apos;t guarantee results, and that I am responsible for this deployment
            {live ? " and every real-money order it places" : ""}.
          </label>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setState("dismissed")}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant={live ? "destructive" : "default"}
              disabled={!ack || (live && (totp.length < 6 || !conn || !user?.totp_enabled))}
              loading={deploy.isPending}
              onClick={() => deploy.mutate()}
            >
              <Rocket /> Confirm {live ? "LIVE" : String(c.mode)} deployment
            </Button>
          </div>
        </div>
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------- portfolio

function PortfolioCard({ c }: { c: Any }) {
  const f = (c.funds ?? {}) as Any;
  const pos = ((c.positions ?? []) as Any[]).filter((p) => p.quantity);
  return (
    <Shell title="Paper portfolio" actions={<OpenLink href="/portfolio">Portfolio</OpenLink>}>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        <Mini label="Available" value={inr(f.available, { compact: true })} />
        <Mini label="Used margin" value={inr(f.used_margin, { compact: true })} />
        <Mini label="Total" value={inr(f.total, { compact: true })} />
        <Mini label="Day P&L" value={<Pnl value={c.day_pnl} />} />
      </div>
      {pos.length > 0 ? (
        <TableCard c={{ title: `Open positions · ${pos.length}`, columns: ["symbol", "quantity", "average_price", "last_price", "unrealised_pnl"], rows: pos }} />
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No open positions.</p>
      )}
    </Shell>
  );
}

function PortfolioAnalysisCard({ c }: { c: Any }) {
  const conc = (c.concentration ?? {}) as Any;
  return (
    <Shell title="Portfolio risk" actions={<OpenLink href="/portfolio">Portfolio</OpenLink>}>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        <Mini label="Gross" value={inr(c.gross_exposure, { compact: true })} />
        <Mini label="Net" value={inr(c.net_exposure, { compact: true })} />
        <Mini label="Beta" value={num(c.portfolio_beta, 2)} />
        <Mini label="Top weight" value={`${num(conc.top_weight_pct, 1)}%`} hint={short(conc.top_symbol)} tone={conc.top_weight_pct > 40 ? "warning" : undefined} />
      </div>
      {((c.by_sector ?? []) as Any[]).length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          {((c.by_sector ?? []) as Any[]).slice(0, 6).map((s) => (
            <div key={s.sector} className="flex items-center gap-2 text-2xs">
              <span className="w-32 truncate">{s.sector}</span>
              <div className="h-1.5 flex-1 rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary" style={{ width: `${s.weight_pct}%` }} />
              </div>
              <span className="num w-10 text-right">{num(s.weight_pct, 0)}%</span>
            </div>
          ))}
        </div>
      )}
      <ul className="mt-2 list-inside list-disc text-2xs text-muted-foreground">
        {((c.observations ?? []) as string[]).map((o, i) => (
          <li key={i}>{o}</li>
        ))}
      </ul>
    </Shell>
  );
}

export function CopilotCard({ card, onAsk }: { card: Card; onAsk?: (q: string) => void }) {
  const c = card as Any;
  switch (card.type) {
    case "quotes":
      return <QuotesCard c={c} />;
    case "chart":
      return <ChartCard c={c} />;
    case "option_chain":
      return <OptionChainCard c={c} />;
    case "payoff":
      return <PayoffCard c={c} />;
    case "fundamentals":
      return <FundamentalsCard c={c} />;
    case "news":
      return <NewsCard c={c} />;
    case "table":
      return <TableCard c={c} />;
    case "kv":
      return <KvCard c={c} />;
    case "screener":
      return <ScreenerCard c={c} />;
    case "strategy":
      return <StrategyCard c={c} onAsk={onAsk} />;
    case "backtest":
      return <BacktestCard c={c} onAsk={onAsk} />;
    case "deploy_confirm":
      return <DeployConfirmCard c={c} />;
    case "portfolio":
      return <PortfolioCard c={c} />;
    case "portfolio_analysis":
      return <PortfolioAnalysisCard c={c} />;
    default:
      return <KvCard c={{ title: card.type, data: card }} />;
  }
}

