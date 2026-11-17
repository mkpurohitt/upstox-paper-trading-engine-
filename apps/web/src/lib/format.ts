const inrFmt = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const inrFmt0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const numFmtCache = new Map<number, Intl.NumberFormat>();

function numFmt(digits: number): Intl.NumberFormat {
  let f = numFmtCache.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    numFmtCache.set(digits, f);
  }
  return f;
}

const isNil = (v: unknown): v is null | undefined => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));

/** ₹1,23,456.78 (Indian digit grouping). */
export function inr(v: number | null | undefined, opts: { compact?: boolean; decimals?: 0 | 2; signed?: boolean } = {}): string {
  if (isNil(v)) return "—";
  const sign = opts.signed && v > 0 ? "+" : "";
  if (opts.compact) return sign + compactInr(v);
  return sign + (opts.decimals === 0 ? inrFmt0 : inrFmt).format(v);
}

/** ₹1.23 Cr / ₹4.5 L / ₹12.3K */
export function compactInr(v: number): string {
  const a = Math.abs(v);
  const s = v < 0 ? "-" : "";
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)} L`;
  if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(1)}K`;
  return `${s}₹${a.toFixed(0)}`;
}

export function num(v: number | null | undefined, digits = 2): string {
  if (isNil(v)) return "—";
  return numFmt(digits).format(v);
}

export function compactNum(v: number | null | undefined): string {
  if (isNil(v)) return "—";
  const a = Math.abs(v);
  const s = v < 0 ? "-" : "";
  if (a >= 1e7) return `${s}${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${s}${(a / 1e5).toFixed(2)}L`;
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(1)}K`;
  return `${s}${a.toFixed(0)}`;
}

export function pct(v: number | null | undefined, digits = 2, signed = true): string {
  if (isNil(v)) return "—";
  const sign = signed && v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

export function signed(v: number | null | undefined, digits = 2): string {
  if (isNil(v)) return "—";
  return `${v > 0 ? "+" : ""}${num(v, digits)}`;
}

export function timeAgo(iso: string | Date): string {
  const t = typeof iso === "string" ? new Date(iso).getTime() : iso.getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function istTime(iso: string | Date, withDate = false): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    ...(withDate ? { day: "2-digit", month: "short" } : {}),
  });
}

export function shortDate(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit", timeZone: "Asia/Kolkata" });
}

/** "NSE:RELIANCE" -> "RELIANCE", "NSE_INDEX:NIFTY" -> "NIFTY" */
export function sym(symbol: string): string {
  const i = symbol.indexOf(":");
  return i >= 0 ? symbol.slice(i + 1) : symbol;
}

export function exch(symbol: string): string {
  const i = symbol.indexOf(":");
  return i >= 0 ? symbol.slice(0, i).replace("_INDEX", "") : "";
}

/** ₹ crore amounts: ₹6.48 L Cr (lakh crore) / ₹12,345 Cr. */
export function croreInr(cr: number | null | undefined): string {
  if (cr === null || cr === undefined || Number.isNaN(cr)) return "—";
  if (Math.abs(cr) >= 1e5) return `₹${(cr / 1e5).toFixed(2)} L Cr`;
  return `₹${Math.round(cr).toLocaleString("en-IN")} Cr`;
}
