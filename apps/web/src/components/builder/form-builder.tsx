"use client";
import { Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { SymbolMultiPicker, SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { useIndicatorCatalog } from "@/hooks/use-catalog";
import { useBuilder } from "@/lib/builder-store";
import { DAYS, PRICE_FIELDS, TIMEFRAMES, emptyGroup, indicatorRefs, slugId, type DSL, type Group, type IndicatorSpec, type Leg } from "@/lib/dsl";
import { cn } from "@/lib/utils";
import { GroupEditor } from "./condition-editor";

function Section({ title, description, children, actions }: { title: string; description?: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle>{title}</CardTitle>
          {description ? <CardDescription className="mt-1">{description}</CardDescription> : null}
        </div>
        {actions}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">{children}</CardContent>
    </Card>
  );
}

function F({ label, children, className, hint }: { label: string; children: React.ReactNode; className?: string; hint?: string }) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label>{label}</Label>
      {children}
      {hint ? <span className="text-2xs text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

function num(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function IndicatorsSection({ dsl, update }: { dsl: DSL; update: (fn: (d: DSL) => void) => void }) {
  const { data: catalog } = useIndicatorCatalog();
  const inds = dsl.indicators ?? [];
  const add = (kind: string) =>
    update((d) => {
      const spec = catalog?.find((c) => c.kind === kind);
      const base = slugId(kind);
      let id = base;
      let n = 2;
      while ((d.indicators ?? []).some((x) => x.id === id)) id = `${base}_${n++}`;
      const params: Record<string, number> = {};
      spec?.params.forEach((p) => (params[p.name] = p.default));
      d.indicators = [...(d.indicators ?? []), { id, kind, params, source: (spec?.default_source as IndicatorSpec["source"]) ?? "close", code: kind === "CUSTOM" ? "def compute(df, params):\n    return df['close'].rolling(10).mean()\n" : null }];
    });
  return (
    <Section
      title="Indicators"
      description="Computed on the strategy timeframe. Reference them in conditions by id."
      actions={
        <Select
          ariaLabel="Add indicator"
          className="h-8 w-44 text-xs"
          value={undefined}
          placeholder="+ Add indicator"
          onValueChange={add}
          options={(catalog ?? []).map((c) => ({ value: c.kind, label: `${c.kind} — ${c.description}` }))}
        />
      }
    >
      {!inds.length && <p className="text-xs text-muted-foreground">No indicators. Price-only and time-based strategies are fine too.</p>}
      {inds.map((ind, i) => {
        const spec = catalog?.find((c) => c.kind === ind.kind);
        return (
          <div key={i} className="flex flex-wrap items-end gap-2 rounded-md border bg-background/50 p-2">
            <F label="id" className="w-32">
              <Input
                className="h-8 text-xs"
                value={ind.id}
                onChange={(e) => update((d) => void (d.indicators![i]!.id = e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_")))}
              />
            </F>
            <Badge className="mb-2">{ind.kind}</Badge>
            {spec?.params.map((p) => (
              <F key={p.name} label={p.name} className="w-24">
                <Input
                  className="h-8 text-xs"
                  type="number"
                  step="any"
                  min={p.min}
                  max={p.max}
                  value={String(ind.params?.[p.name] ?? p.default)}
                  onChange={(e) => update((d) => void (d.indicators![i]!.params = { ...d.indicators![i]!.params, [p.name]: Number(e.target.value) }))}
                />
              </F>
            ))}
            {ind.kind !== "CUSTOM" && spec && !["VWAP", "OBV", "PIVOTS", "CPR", "HEIKIN_ASHI"].includes(ind.kind) && (
              <F label="source" className="w-24">
                <Select className="h-8 text-xs" value={ind.source ?? "close"} onValueChange={(v) => update((d) => void (d.indicators![i]!.source = v as IndicatorSpec["source"]))} options={PRICE_FIELDS.map((f) => ({ value: f, label: f }))} />
              </F>
            )}
            {spec && spec.outputs.length > 1 && <span className="mb-2 text-2xs text-muted-foreground">outputs: {spec.outputs.join(", ")}</span>}
            <Button variant="ghost" size="icon-sm" className="mb-0.5 ml-auto text-muted-foreground hover:text-loss" aria-label="Remove indicator" onClick={() => update((d) => void d.indicators!.splice(i, 1))}>
              <Trash2 />
            </Button>
            {ind.kind === "CUSTOM" && (
              <F label="Python (sandboxed): def compute(df, params) -> series" className="w-full">
                <Textarea className="min-h-[96px] font-mono text-xs" value={ind.code ?? ""} onChange={(e) => update((d) => void (d.indicators![i]!.code = e.target.value))} spellCheck={false} />
              </F>
            )}
          </div>
        );
      })}
    </Section>
  );
}

function RulesSection({ dsl, update, which }: { dsl: DSL; update: (fn: (d: DSL) => void) => void; which: "entry" | "exit" }) {
  const { data: catalog } = useIndicatorCatalog();
  const refs = indicatorRefs(dsl, catalog);
  const rules = (dsl[which] ?? {}) as { long?: Group | null; short?: Group | null };
  return (
    <Section
      title={which === "entry" ? "Entry rules" : "Exit rules"}
      description={which === "entry" ? "Evaluated on each bar close. Long and short are independent." : "Signal exits in addition to stop-loss / target below."}
    >
      {(["long", "short"] as const).map((side) => {
        const g = rules[side];
        return (
          <div key={side} className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Switch
                checked={!!g}
                aria-label={`${which} ${side}`}
                onCheckedChange={(on) => update((d) => void ((d[which] as Record<string, unknown>)[side] = on ? emptyGroup(which === "entry" ? "all" : "any") : null))}
              />
              <span className={cn("text-xs font-semibold uppercase", side === "long" ? "text-profit" : "text-loss")}>{side}</span>
            </div>
            {g && <GroupEditor group={g} refs={refs} onChange={(ng) => update((d) => void ((d[which] as Record<string, unknown>)[side] = ng))} />}
          </div>
        );
      })}
      {which === "exit" && (
        <div className="grid gap-3 border-t pt-3 sm:grid-cols-2 lg:grid-cols-4">
          {(["stop_loss", "target"] as const).map((k) => {
            const spec = dsl.exit?.[k];
            return (
              <F key={k} label={k === "stop_loss" ? "Stop loss" : "Target"}>
                <div className="flex gap-1">
                  <Select
                    className="h-8 w-28 text-xs"
                    value={spec?.type ?? "none"}
                    onValueChange={(t) => update((d) => void ((d.exit ??= {})[k] = t === "none" ? null : { type: t as "percent", value: spec?.value ?? 1, atr_period: 14 }))}
                    options={[{ value: "none", label: "None" }, { value: "percent", label: "%" }, { value: "points", label: "Points" }, { value: "atr", label: "× ATR" }]}
                  />
                  {spec && <Input className="h-8 text-xs" type="number" step="any" value={spec.value} onChange={(e) => update((d) => void (d.exit![k]!.value = Number(e.target.value)))} />}
                </div>
              </F>
            );
          })}
          <F label="Trailing stop (%)" hint="activates after profit %">
            <div className="flex gap-1">
              <Input className="h-8 text-xs" type="number" step="any" placeholder="off" value={dsl.exit?.trailing_sl?.value ?? ""} onChange={(e) => update((d) => void ((d.exit ??= {}).trailing_sl = num(e.target.value) ? { type: "percent", value: num(e.target.value)!, activate_after: d.exit?.trailing_sl?.activate_after ?? 0 } : null))} />
              <Input className="h-8 text-xs" type="number" step="any" placeholder="after" value={dsl.exit?.trailing_sl?.activate_after ?? ""} disabled={!dsl.exit?.trailing_sl} onChange={(e) => update((d) => void (d.exit!.trailing_sl!.activate_after = Number(e.target.value)))} />
            </div>
          </F>
          <F label="Max holding (bars)">
            <Input className="h-8 text-xs" type="number" placeholder="unlimited" value={dsl.exit?.max_holding_bars ?? ""} onChange={(e) => update((d) => void ((d.exit ??= {}).max_holding_bars = num(e.target.value)))} />
          </F>
        </div>
      )}
    </Section>
  );
}

function LegsSection({ dsl, update }: { dsl: DSL; update: (fn: (d: DSL) => void) => void }) {
  const legs = dsl.legs ?? [];
  const ox = dsl.options_exit ?? {};
  return (
    <Section
      title="Option legs"
      description="Strikes are picked at entry time from the live / historical chain."
      actions={
        <Button size="xs" variant="outline" onClick={() => update((d) => void (d.legs = [...(d.legs ?? []), { id: `leg${(d.legs?.length ?? 0) + 1}`, action: "SELL", option_type: "CE", strike: { mode: "ATM_OFFSET", offset: 0 }, expiry: "current", lots: 1 }]))}>
          <Plus /> Leg
        </Button>
      }
    >
      <F label="Underlying" className="max-w-xs">
        <Select
          value={dsl.universe?.underlying ?? "NIFTY"}
          onValueChange={(u) => update((d) => void ((d.universe ??= {}).underlying = u))}
          options={["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "RELIANCE", "HDFCBANK", "INFY", "SBIN", "TCS"].map((x) => ({ value: x, label: x }))}
        />
      </F>
      {legs.map((leg, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2 rounded-md border bg-background/50 p-2">
          <F label="id" className="w-20">
            <Input className="h-8 text-xs" value={leg.id ?? ""} onChange={(e) => update((d) => void (d.legs![i]!.id = e.target.value.replace(/[^a-z0-9_]/gi, "_")))} />
          </F>
          <F label="Action" className="w-20">
            <Select className={cn("h-8 text-xs", leg.action === "BUY" ? "text-profit" : "text-loss")} value={leg.action} onValueChange={(v) => update((d) => void (d.legs![i]!.action = v as Leg["action"]))} options={[{ value: "BUY", label: "BUY" }, { value: "SELL", label: "SELL" }]} />
          </F>
          <F label="Type" className="w-20">
            <Select className="h-8 text-xs" value={leg.option_type} onValueChange={(v) => update((d) => void (d.legs![i]!.option_type = v as Leg["option_type"]))} options={[{ value: "CE", label: "CE" }, { value: "PE", label: "PE" }]} />
          </F>
          <F label="Strike by" className="w-28">
            <Select className="h-8 text-xs" value={leg.strike?.mode ?? "ATM_OFFSET"} onValueChange={(v) => update((d) => void (d.legs![i]!.strike = { mode: v as "ATM_OFFSET", offset: 0, delta: v === "DELTA" ? 0.25 : null, premium: v === "PREMIUM" ? 50 : null }))} options={[{ value: "ATM_OFFSET", label: "ATM ± n" }, { value: "DELTA", label: "Delta" }, { value: "PREMIUM", label: "Premium ₹" }]} />
          </F>
          <F label={leg.strike?.mode === "DELTA" ? "Delta" : leg.strike?.mode === "PREMIUM" ? "Premium" : "Offset"} className="w-20">
            <Input
              className="h-8 text-xs"
              type="number"
              step="any"
              value={leg.strike?.mode === "DELTA" ? leg.strike.delta ?? 0.25 : leg.strike?.mode === "PREMIUM" ? leg.strike.premium ?? 50 : leg.strike?.offset ?? 0}
              onChange={(e) =>
                update((d) => {
                  const s = d.legs![i]!.strike!;
                  const v = Number(e.target.value);
                  if (s.mode === "DELTA") s.delta = v;
                  else if (s.mode === "PREMIUM") s.premium = v;
                  else s.offset = Math.round(v);
                })
              }
            />
          </F>
          <F label="Expiry" className="w-24">
            <Select className="h-8 text-xs" value={leg.expiry ?? "current"} onValueChange={(v) => update((d) => void (d.legs![i]!.expiry = v as Leg["expiry"]))} options={[{ value: "current", label: "Current" }, { value: "next", label: "Next" }, { value: "monthly", label: "Monthly" }]} />
          </F>
          <F label="Lots" className="w-16">
            <Input className="h-8 text-xs" type="number" min={1} value={leg.lots ?? 1} onChange={(e) => update((d) => void (d.legs![i]!.lots = Math.max(1, Number(e.target.value))))} />
          </F>
          <F label="Leg SL %" className="w-20">
            <Input className="h-8 text-xs" type="number" placeholder="—" value={leg.stop_loss_pct ?? ""} onChange={(e) => update((d) => void (d.legs![i]!.stop_loss_pct = num(e.target.value)))} />
          </F>
          <Button variant="ghost" size="icon-sm" className="mb-0.5 ml-auto text-muted-foreground hover:text-loss" aria-label="Remove leg" onClick={() => update((d) => void d.legs!.splice(i, 1))}>
            <Trash2 />
          </Button>
        </div>
      ))}
      <div className="grid gap-3 border-t pt-3 sm:grid-cols-2 lg:grid-cols-5">
        {(
          [
            ["combined_stop_loss_pct", "Combined SL (% of premium)"],
            ["combined_target_pct", "Target (% premium captured)"],
            ["stop_loss_amount", "MTM stop (₹)"],
            ["target_amount", "MTM target (₹)"],
          ] as const
        ).map(([k, label]) => (
          <F key={k} label={label}>
            <Input className="h-8 text-xs" type="number" placeholder="off" value={(ox as Record<string, number | null | undefined>)[k] ?? ""} onChange={(e) => update((d) => void ((d.options_exit ??= {})[k] = num(e.target.value)))} />
          </F>
        ))}
        <F label="Exit on expiry day at">
          <Input className="h-8 text-xs" type="time" value={ox.exit_on_expiry_day_at ?? ""} onChange={(e) => update((d) => void ((d.options_exit ??= {}).exit_on_expiry_day_at = e.target.value || null))} />
        </F>
      </div>
    </Section>
  );
}

export function FormBuilder() {
  const dsl = useBuilder((s) => s.dsl);
  const update = useBuilder((s) => s.update);
  const kind = dsl.kind ?? "equity";
  return (
    <div className="flex flex-col gap-3">
      <Section title="Basics">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Name" className="sm:col-span-2">
            <Input value={dsl.name} onChange={(e) => update((d) => void (d.name = e.target.value))} maxLength={120} />
          </F>
          <F label="Type">
            <Select
              value={kind}
              onValueChange={(k) => update((d) => void (d.kind = k as DSL["kind"]))}
              options={[{ value: "equity", label: "Equity / Futures" }, { value: "options", label: "Options (multi-leg)" }, { value: "pair", label: "Pair trade" }]}
            />
          </F>
          <F label="Timeframe">
            <Select value={dsl.timeframe ?? "15m"} onValueChange={(t) => update((d) => void (d.timeframe = t as DSL["timeframe"]))} options={TIMEFRAMES.map((t) => ({ value: t, label: t }))} />
          </F>
          <F label="Description" className="sm:col-span-2 lg:col-span-3">
            <Input value={dsl.description ?? ""} onChange={(e) => update((d) => void (d.description = e.target.value))} placeholder="What is the edge?" />
          </F>
          <F label="Product">
            <Select value={dsl.product ?? "MIS"} onValueChange={(p) => update((d) => void (d.product = p as DSL["product"]))} options={[{ value: "MIS", label: "MIS (intraday)" }, { value: "CNC", label: "CNC (delivery)" }, { value: "NRML", label: "NRML (F&O carry)" }]} />
          </F>
        </div>
        {kind === "equity" && (
          <F label="Universe" hint="Cash equities, indices (signal only) or futures contracts">
            <SymbolMultiPicker value={dsl.universe?.symbols ?? []} onChange={(v) => update((d) => void ((d.universe ??= {}).symbols = v))} />
          </F>
        )}
      </Section>

      {kind !== "pair" && <IndicatorsSection dsl={dsl} update={update} />}
      {kind === "equity" && <RulesSection dsl={dsl} update={update} which="entry" />}
      {kind === "equity" && <RulesSection dsl={dsl} update={update} which="exit" />}
      {kind === "options" && <LegsSection dsl={dsl} update={update} />}
      {kind === "options" && (
        <Section title="Entry filter (optional)" description="Conditions on the underlying that must hold at entry time, e.g. VWAP or RSI filters.">
          <RulesSectionLongOnly dsl={dsl} update={update} />
        </Section>
      )}
      {kind === "pair" && (
        <Section title="Pair settings" description="Log-price spread with rolling OLS hedge ratio; z-score bands.">
          <div className="grid gap-3 sm:grid-cols-2">
            <F label="Leg A (long when spread is cheap)">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{dsl.pair?.leg_a}</Badge>
                <SymbolSearch className="flex-1" onPick={(s) => update((d) => void ((d.pair ??= { leg_a: s, leg_b: "" }).leg_a = s))} placeholder="Change leg A" />
              </div>
            </F>
            <F label="Leg B">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{dsl.pair?.leg_b}</Badge>
                <SymbolSearch className="flex-1" onPick={(s) => update((d) => void ((d.pair ??= { leg_a: "", leg_b: s }).leg_b = s))} placeholder="Change leg B" />
              </div>
            </F>
          </div>
          <div className="grid gap-3 sm:grid-cols-5">
            {(["lookback", "entry_z", "exit_z", "stop_z"] as const).map((k) => (
              <F key={k} label={k.replace("_", " ")}>
                <Input className="h-8 text-xs" type="number" step="any" value={dsl.pair?.[k] ?? ""} onChange={(e) => update((d) => void ((d.pair as Record<string, unknown>)[k] = num(e.target.value)))} />
              </F>
            ))}
            <F label="Max holding bars">
              <Input className="h-8 text-xs" type="number" value={dsl.exit?.max_holding_bars ?? ""} onChange={(e) => update((d) => void ((d.exit ??= {}).max_holding_bars = num(e.target.value)))} />
            </F>
          </div>
        </Section>
      )}

      <Section title="Sizing, schedule & risk">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Position sizing">
            <div className="flex gap-1">
              <Select
                className="w-36"
                value={dsl.sizing?.mode ?? "capital_pct"}
                onValueChange={(m) => update((d) => void (d.sizing = { mode: m as "capital_pct", value: d.sizing?.value ?? 10 }))}
                options={[{ value: "capital_pct", label: "% of capital" }, { value: "fixed_capital", label: "₹ per trade" }, { value: "fixed_qty", label: "Fixed qty" }, { value: "fixed_lots", label: "Lots / multiplier" }]}
              />
              <Input type="number" step="any" value={dsl.sizing?.value ?? 10} onChange={(e) => update((d) => void ((d.sizing ??= { mode: "capital_pct", value: 10 }).value = Number(e.target.value)))} />
            </div>
          </F>
          <F label="Entry window (IST)">
            <div className="flex gap-1">
              <Input type="time" value={dsl.schedule?.entry_after ?? ""} onChange={(e) => update((d) => void ((d.schedule ??= {}).entry_after = e.target.value || null))} aria-label="Entry after" />
              <Input type="time" value={dsl.schedule?.entry_before ?? ""} onChange={(e) => update((d) => void ((d.schedule ??= {}).entry_before = e.target.value || null))} aria-label="Entry before" />
            </div>
          </F>
          <F label="Square-off (MIS)">
            <Input type="time" value={dsl.schedule?.square_off ?? ""} onChange={(e) => update((d) => void ((d.schedule ??= {}).square_off = e.target.value || null))} />
          </F>
          <F label="Trading days">
            <div className="flex gap-1">
              {DAYS.map((day) => {
                const days = dsl.schedule?.days ?? [...DAYS];
                const on = days.includes(day);
                return (
                  <button key={day} type="button" aria-pressed={on} onClick={() => update((d) => void ((d.schedule ??= {}).days = on ? days.filter((x) => x !== day) : [...days, day]))} className={cn("h-9 flex-1 rounded-md text-2xs font-semibold", on ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground")}>
                    {day[0]}
                  </button>
                );
              })}
            </div>
          </F>
          <F label="Max loss / day (₹)">
            <Input type="number" placeholder="none" value={dsl.risk?.max_loss_per_day ?? ""} onChange={(e) => update((d) => void ((d.risk ??= {}).max_loss_per_day = num(e.target.value)))} />
          </F>
          <F label="Max trades / day">
            <Input type="number" placeholder="none" value={dsl.risk?.max_trades_per_day ?? ""} onChange={(e) => update((d) => void ((d.risk ??= {}).max_trades_per_day = num(e.target.value)))} />
          </F>
          <F label="Portfolio max loss (₹)" hint="halts the strategy">
            <Input type="number" placeholder="none" value={dsl.risk?.portfolio_max_loss ?? ""} onChange={(e) => update((d) => void ((d.risk ??= {}).portfolio_max_loss = num(e.target.value)))} />
          </F>
          <F label="Re-entry after SL">
            <div className="flex items-center gap-2">
              <Switch checked={!!dsl.reentry?.enabled} onCheckedChange={(on) => update((d) => void (d.reentry = { enabled: on, max_per_day: d.reentry?.max_per_day ?? 1, cooldown_bars: d.reentry?.cooldown_bars ?? 0 }))} />
              <Input className="h-8 w-16 text-xs" type="number" aria-label="Max re-entries" title="max re-entries/day" disabled={!dsl.reentry?.enabled} value={dsl.reentry?.max_per_day ?? 1} onChange={(e) => update((d) => void (d.reentry!.max_per_day = Number(e.target.value)))} />
              <Input className="h-8 w-16 text-xs" type="number" aria-label="Cooldown bars" title="cooldown bars" disabled={!dsl.reentry?.enabled} value={dsl.reentry?.cooldown_bars ?? 0} onChange={(e) => update((d) => void (d.reentry!.cooldown_bars = Number(e.target.value)))} />
            </div>
          </F>
        </div>
      </Section>
    </div>
  );
}

function RulesSectionLongOnly({ dsl, update }: { dsl: DSL; update: (fn: (d: DSL) => void) => void }) {
  const { data: catalog } = useIndicatorCatalog();
  const refs = indicatorRefs(dsl, catalog);
  const g = dsl.entry?.long;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Switch checked={!!g} aria-label="Entry filter" onCheckedChange={(on) => update((d) => void ((d.entry ??= {}).long = on ? emptyGroup("all") : null))} />
        <span className="text-xs text-muted-foreground">{g ? "Enter only when:" : "Time-based entry (no filter)"}</span>
      </div>
      {g && <GroupEditor group={g} refs={refs} onChange={(ng) => update((d) => void ((d.entry ??= {}).long = ng))} />}
    </div>
  );
}
