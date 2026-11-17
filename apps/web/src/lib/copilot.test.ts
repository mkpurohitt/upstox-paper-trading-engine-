import { afterEach, describe, expect, it, vi } from "vitest";
import { withCitationLinks } from "@/components/copilot/message";
import { type ChatEvent, streamChat, toolLabel } from "./copilot";

function sseResponse(chunks: string[], status = 200): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => vi.restoreAllMocks());

describe("streamChat", () => {
  it("parses SSE frames split across network chunks", async () => {
    const frames = [
      { type: "start", session_id: 7, user_message_id: 1, title: "t" },
      { type: "delta", text: "Hello " },
      { type: "delta", text: "world" },
      { type: "done", session_id: 7, message_id: 2, content: "Hello world", citations: [], suggestions: [], cards: [], flags: [], provider: "mock", model: "m", usage: { tokens_in: 1, tokens_out: 2, cost_usd: 0 } },
    ];
    const raw = frames.map((f) => `event: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`).join("");
    // split at awkward offsets, including inside a JSON payload and between the two newlines
    const parts = [raw.slice(0, 17), raw.slice(17, 90), raw.slice(90, raw.indexOf("\n\n", 100) + 1), raw.slice(raw.indexOf("\n\n", 100) + 1)];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse(parts));
    const got: ChatEvent[] = [];
    await streamChat({ message: "hi" }, (e) => got.push(e));
    expect(got.map((e) => e.type)).toEqual(["start", "delta", "delta", "done"]);
    expect(got.filter((e) => e.type === "delta").map((e) => (e as { text: string }).text).join("")).toBe("Hello world");
  });

  it("throws the API error message on non-2xx", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "Plan limit reached" } }), { status: 402, headers: { "Content-Type": "application/json" } }),
    );
    await expect(streamChat({ message: "hi" }, () => undefined)).rejects.toThrow("Plan limit reached");
  });
});

describe("citations and labels", () => {
  it("links bare [n] markers but leaves markdown links alone", () => {
    expect(withCitationLinks("Max pain is X [1] and Y [2].")).toBe("Max pain is X [1](#cite-1) and Y [2](#cite-2).");
    expect(withCitationLinks("see [docs](https://x.y) and [3](#cite-3)")).toBe("see [docs](https://x.y) and [3](#cite-3)");
  });

  it("labels tools, including dynamic NSE tools", () => {
    expect(toolLabel("run_backtest")).toBe("Backtesting");
    expect(toolLabel("nse_get_fii_dii_activity")).toBe("NSE · fii dii activity");
  });
});
