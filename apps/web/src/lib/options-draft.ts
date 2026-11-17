import { DRAFT_KEY } from "@/lib/builder-store";
import type { PayoffLeg } from "@/lib/options";

/** Turn priced legs into an options-strategy DSL draft (ATM-offset strikes) and hand it to /build. */
export function optionsDraft(underlying: string, legs: PayoffLeg[], atm: number, step: number, name?: string) {
  const intraday = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"].includes(underlying);
  return {
    dsl_version: "1.0",
    name: name ?? `${underlying} ${legs.length}-leg structure`,
    kind: "options",
    description: "Created from the Analysis options builder. Strikes are ATM-relative so the structure re-centres each entry.",
    universe: { underlying },
    timeframe: "5m",
    product: intraday ? "MIS" : "NRML",
    legs: legs
      .filter((l) => l.option_type !== "FUT")
      .map((l, i) => ({
        id: `leg${i + 1}`,
        action: l.action,
        option_type: l.option_type,
        strike: { mode: "ATM_OFFSET", offset: Math.max(-30, Math.min(30, Math.round((l.strike - atm) / (step || 1)))) },
        expiry: "current",
        lots: l.lots,
      })),
    options_exit: { combined_stop_loss_pct: 50, combined_target_pct: 50 },
    sizing: { mode: "fixed_lots", value: 1 },
    schedule: { entry_after: "09:20", entry_before: "10:30", square_off: intraday ? "15:15" : null },
    reentry: { enabled: false, max_per_day: 0, cooldown_bars: 0 },
    tags: ["options", "from-analysis"],
  };
}

export function sendDraftToBuilder(draft: unknown, push: (url: string) => void) {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    /* storage unavailable: builder will open blank */
  }
  push("/build/new?draft=1");
}
