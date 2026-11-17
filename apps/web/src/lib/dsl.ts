/**
 * Strategy DSL types (generated from the backend Pydantic models) + helpers
 * shared by the form, visual and code builders.
 */
import type { Schemas } from "@algo/api-client";

export type DSL = Schemas["StrategyDSL"];
export type Group = Schemas["GroupCondition"];
export type Compare = Schemas["CompareCondition"];
export type TimeCond = Schemas["TimeCondition"];
export type DayCond = Schemas["DayCondition"];
export type PatternCond = Schemas["PatternCondition"];
export type Condition = Group | Compare | TimeCond | DayCond | PatternCond;
export type Operand = Schemas["IndicatorOperand"] | Schemas["PriceOperand"] | Schemas["ConstOperand"];
export type IndicatorSpec = Schemas["IndicatorSpec"];
export type Leg = Schemas["OptionLegSpec"];
export type IndicatorCatalog = Schemas["IndicatorCatalogItem"];
export type Kind = "equity" | "options" | "pair";

export const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "1d"] as const;
export const OPS = [">", "<", ">=", "<=", "==", "crosses_above", "crosses_below"] as const;
export const PRICE_FIELDS = ["open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4"] as const;
export const PATTERNS = [
  "doji", "hammer", "inverted_hammer", "shooting_star", "bullish_engulfing", "bearish_engulfing", "morning_star",
  "evening_star", "inside_bar", "outside_bar", "three_white_soldiers", "three_black_crows", "breakout_high",
  "breakdown_low", "gap_up", "gap_down",
] as const;
export const DAYS = ["MON", "TUE", "WED", "THU", "FRI"] as const;
export const BROKERS = ["zerodha", "upstox", "angel", "dhan", "fyers", "kotak", "fivepaisa", "icici", "aliceblue", "shoonya", "paper"] as const;

export const OP_LABEL: Record<string, string> = {
  ">": ">", "<": "<", ">=": "≥", "<=": "≤", "==": "=", crosses_above: "crosses above", crosses_below: "crosses below",
};

export function emptyGroup(kind: "all" | "any" = "all"): Group {
  return { kind, conditions: [] };
}

export function blankDsl(kind: Kind = "equity"): DSL {
  const base: DSL = {
    dsl_version: "1.0",
    name: kind === "options" ? "New options strategy" : kind === "pair" ? "New pair trade" : "New strategy",
    description: "",
    kind,
    universe: kind === "options" ? { symbols: [], underlying: "NIFTY" } : { symbols: kind === "pair" ? ["NSE:HDFCBANK", "NSE:ICICIBANK"] : ["NSE:RELIANCE"] },
    timeframe: kind === "pair" ? "1d" : kind === "options" ? "5m" : "15m",
    product: kind === "pair" ? "CNC" : "MIS",
    indicators: kind === "equity" ? [{ id: "ema_fast", kind: "EMA", params: { period: 9 }, source: "close" }, { id: "ema_slow", kind: "EMA", params: { period: 21 }, source: "close" }] : [],
    entry: kind === "equity" ? { long: { kind: "all", conditions: [{ kind: "compare", left: { type: "indicator", ref: "ema_fast", offset: 0 }, op: "crosses_above", right: { type: "indicator", ref: "ema_slow", offset: 0 } }] } } : {},
    exit: kind === "equity" ? { long: { kind: "any", conditions: [{ kind: "compare", left: { type: "indicator", ref: "ema_fast", offset: 0 }, op: "crosses_below", right: { type: "indicator", ref: "ema_slow", offset: 0 } }] }, stop_loss: { type: "percent", value: 1, atr_period: 14 }, target: { type: "percent", value: 2, atr_period: 14 } } : {},
    legs: kind === "options" ? [
      { id: "ce", action: "SELL", option_type: "CE", strike: { mode: "ATM_OFFSET", offset: 0 }, expiry: "current", lots: 1, stop_loss_pct: 30 },
      { id: "pe", action: "SELL", option_type: "PE", strike: { mode: "ATM_OFFSET", offset: 0 }, expiry: "current", lots: 1, stop_loss_pct: 30 },
    ] : [],
    options_exit: {},
    pair: kind === "pair" ? { leg_a: "NSE:HDFCBANK", leg_b: "NSE:ICICIBANK", lookback: 60, entry_z: 2, exit_z: 0.5, stop_z: 4, hedge: "ols" } : null,
    sizing: kind === "options" ? { mode: "fixed_lots", value: 1 } : { mode: "capital_pct", value: 20 },
    schedule: kind === "pair" ? { entry_after: null, entry_before: null, square_off: null, days: [...DAYS] } : { entry_after: "09:20", entry_before: "15:00", square_off: "15:15", days: [...DAYS] },
    reentry: { enabled: false, max_per_day: 1, cooldown_bars: 0 },
    risk: {},
    tags: [],
  };
  return base;
}

/** All operand refs selectable in condition editors (multi-output indicators expanded). */
export function indicatorRefs(dsl: DSL, catalog: IndicatorCatalog[] | undefined): string[] {
  const out: string[] = [];
  for (const ind of dsl.indicators ?? []) {
    const spec = catalog?.find((c) => c.kind === ind.kind);
    if (spec && spec.outputs.length > 1) spec.outputs.forEach((o) => out.push(`${ind.id}.${o}`));
    else out.push(ind.id);
  }
  return out;
}

export function operandLabel(o: Operand): string {
  if (o.type === "const") return String(o.value);
  const off = o.offset ? `[${o.offset}]` : "";
  return o.type === "price" ? `${o.field ?? "close"}${off}` : `${o.ref}${off}`;
}

export function describe(c: Condition | null | undefined): string {
  if (!c) return "—";
  switch (c.kind) {
    case "all":
    case "any": {
      const g = c as Group;
      const parts = (g.conditions ?? []).map((x) => describe(x as Condition));
      if (!parts.length) return c.kind === "all" ? "always" : "never";
      return parts.length === 1 ? parts[0]! : `(${parts.join(c.kind === "all" ? " AND " : " OR ")})`;
    }
    case "compare": {
      const x = c as Compare;
      return `${operandLabel(x.left as Operand)} ${OP_LABEL[x.op] ?? x.op} ${operandLabel(x.right as Operand)}`;
    }
    case "time": {
      const t = c as TimeCond;
      return `time ${t.after ? `≥ ${t.after}` : ""}${t.after && t.before ? " and " : ""}${t.before ? `< ${t.before}` : ""}`;
    }
    case "day_of_week":
      return `day in ${(c as DayCond).days.join("/")}`;
    case "pattern":
      return `pattern ${(c as PatternCond).name.replace(/_/g, " ")}`;
    default:
      return "?";
  }
}

/** Optimisable numeric parameters derived from the DSL (for the optimise / walk-forward tabs). */
export function tunableParams(dsl: DSL, catalog: IndicatorCatalog[] | undefined): { path: string; label: string; value: number; min: number; max: number }[] {
  const out: { path: string; label: string; value: number; min: number; max: number }[] = [];
  for (const ind of dsl.indicators ?? []) {
    const spec = catalog?.find((c) => c.kind === ind.kind);
    for (const p of spec?.params ?? []) {
      const v = Number(ind.params?.[p.name] ?? p.default);
      out.push({ path: `indicators.${ind.id}.params.${p.name}`, label: `${ind.id}.${p.name}`, value: v, min: p.min, max: p.max });
    }
  }
  const ex = dsl.exit ?? {};
  if (ex.stop_loss) out.push({ path: "exit.stop_loss.value", label: "stop loss", value: ex.stop_loss.value, min: 0.1, max: 20 });
  if (ex.target) out.push({ path: "exit.target.value", label: "target", value: ex.target.value, min: 0.1, max: 50 });
  if (dsl.pair) {
    out.push({ path: "pair.entry_z", label: "entry z", value: dsl.pair.entry_z ?? 2, min: 0.5, max: 4 });
    out.push({ path: "pair.lookback", label: "lookback", value: dsl.pair.lookback ?? 60, min: 10, max: 250 });
  }
  return out;
}

export function slugId(s: string): string {
  const id = s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 28);
  return /^[a-z]/.test(id) ? id : `i_${id}`;
}

/** Set a dotted path in a DSL copy; list items are addressed by their `id` (mirrors the backend). */
export function setPath(dsl: DSL, path: string, value: unknown): DSL {
  const out = structuredClone(dsl) as unknown as Record<string, unknown>;
  const parts = path.split(".");
  let cur: unknown = out;
  for (const part of parts.slice(0, -1)) {
    if (Array.isArray(cur)) cur = cur.find((x: { id?: string }) => x.id === part);
    else {
      const obj = cur as Record<string, unknown>;
      obj[part] ??= {};
      cur = obj[part];
    }
  }
  (cur as Record<string, unknown>)[parts[parts.length - 1]!] = value;
  return out as unknown as DSL;
}
