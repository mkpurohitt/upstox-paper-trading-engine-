"use client";
/** Copilot client: types for streamed events / cards and an SSE reader over fetch (POST + auth + abort). */
import { ApiError, apiFetch } from "@/lib/api";

export interface Citation {
  n: number;
  chunk_id: number;
  document_id: number;
  title: string;
  heading: string | null;
  source_url: string | null;
  source_type: string;
  snippet: string;
  score: number;
}

export type Card = { type: string; tool?: string } & Record<string, unknown>;

export interface ToolRun {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  status: "running" | "ok" | "error";
  error?: string | null;
}

export interface ChatMessageUI {
  id: string | number;
  role: "user" | "assistant";
  content: string;
  cards: Card[];
  citations: Citation[];
  suggestions: string[];
  tools: ToolRun[];
  streaming?: boolean;
  error?: string | null;
  model?: string | null;
  flags?: string[];
  createdAt?: string;
}

export type ChatEvent =
  | { type: "start"; session_id: number; user_message_id: number; title: string }
  | { type: "delta"; text: string }
  | { type: "tool_start"; id: string; name: string; args: Record<string, unknown> }
  | { type: "tool_end"; id: string; name: string; ok: boolean; card: Card | null; error?: string | null }
  | { type: "replace"; text: string }
  | {
      type: "done";
      session_id: number;
      message_id: number | null;
      content: string;
      citations: Citation[];
      suggestions: string[];
      cards: Card[];
      flags: string[];
      provider: string;
      model: string;
      usage: { tokens_in: number; tokens_out: number; cost_usd: number };
    }
  | { type: "error"; message: string };

/** POST /api/ai/chat and dispatch Server-Sent Events as they arrive. */
export async function streamChat(
  body: { message: string; session_id?: number | null; context?: string | null },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const j = (await res.json().catch(() => null)) as { error?: { message?: string }; detail?: string } | null;
    throw new ApiError(j?.error?.message ?? (typeof j?.detail === "string" ? j.detail : `Request failed (${res.status})`), res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data: "))
        .map((l) => l.slice(6))
        .join("\n");
      if (data) {
        try {
          onEvent(JSON.parse(data) as ChatEvent);
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}

export const TOOL_LABELS: Record<string, string> = {
  get_quote: "Fetching quotes",
  get_candles: "Reading the chart",
  get_option_chain: "Loading the option chain",
  get_greeks: "Pricing the structure",
  get_fundamentals: "Pulling fundamentals",
  get_news: "Scanning news",
  run_screener: "Running the screener",
  run_scanner: "Running the scanner",
  generate_strategy: "Drafting the strategy",
  run_backtest: "Backtesting",
  get_portfolio: "Reading your portfolio",
  analyze_portfolio: "Analysing portfolio risk",
  deploy_strategy: "Preparing deployment",
};

export function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name]!;
  if (name.startsWith("nse_")) return `NSE · ${name.replace(/^nse_get_/, "").replace(/_/g, " ")}`;
  return name.replace(/_/g, " ");
}

export const QUICK_PROMPTS: { group: string; prompts: string[] }[] = [
  { group: "Markets", prompts: ["NIFTY option chain summary", "FII/DII activity this week", "Market breadth today", "Latest market news"] },
  { group: "Research", prompts: ["Fundamentals of Infosys vs peers", "Technical view on Reliance (daily)", "Find oversold stocks with ROE above 15", "Which bank stocks are cointegrated?"] },
  { group: "Strategies", prompts: ["Backtest an EMA 20/50 crossover on RELIANCE daily", "Build a short straddle on NIFTY with 30% SL", "Show me an iron condor on BANKNIFTY", "Analyze my portfolio"] },
  { group: "Learn", prompts: ["What is max pain?", "Explain theta decay", "What are SEBI's rules for retail algos?", "What is STT on options?"] },
];
