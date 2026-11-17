"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, History, Paperclip, Sparkles, Square, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Disclaimer } from "@/components/common";
import { HistorySidebar } from "@/components/copilot/history";
import { MessageView } from "@/components/copilot/message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import { api, ApiError, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { type Card, type ChatEvent, type ChatMessageUI, type Citation, QUICK_PROMPTS, streamChat } from "@/lib/copilot";
import { usePrefs } from "@/lib/prefs";
import { cn } from "@/lib/utils";

type ServerMessage = { id: number; role: string; content: string; cards?: unknown[]; citations?: unknown[]; suggestions?: unknown[]; tool_calls?: { name?: string; ok?: boolean }[]; model?: string | null; created_at: string };

function fromServer(m: ServerMessage): ChatMessageUI {
  return {
    id: m.id,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    cards: (m.cards ?? []) as Card[],
    citations: (m.citations ?? []) as Citation[],
    suggestions: (m.suggestions ?? []) as string[],
    tools: (m.tool_calls ?? []).map((t, i) => ({ id: `${m.id}-${i}`, name: t.name ?? "tool", status: t.ok === false ? "error" : "ok" })),
    model: m.model,
    createdAt: m.created_at,
  };
}

function Welcome({ onAsk }: { onAsk: (q: string) => void }) {
  const user = useAuth((s) => s.user);
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => unwrap(api.GET("/api/ai/status")), staleTime: 60_000 });
  const first = (user?.full_name ?? "").split(" ")[0];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 py-6 sm:py-12">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-info text-white shadow-lg shadow-primary/20">
        <Sparkles className="h-6 w-6" />
      </div>
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">{first ? `Hi ${first}, what are we researching?` : "What are we researching today?"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">Live market data, option analytics, NSE data, screeners, strategy drafting, backtests and your portfolio — with sources.</p>
        {status.data && (
          <div className="mt-2 flex flex-wrap justify-center gap-1.5 text-2xs">
            <Badge variant={status.data.llm_configured ? "profit" : "secondary"}>
              {status.data.llm_configured ? `Model: ${String(status.data.providers[0]?.strong_model ?? "configured")}` : "Offline assistant (no LLM key configured)"}
            </Badge>
            <Badge variant="outline">
              {status.data.rag_documents} knowledge docs · {status.data.rag_chunks} chunks
            </Badge>
            <Badge variant="outline">
              {status.data.queries_today}/{status.data.limit_per_day} questions today
            </Badge>
          </div>
        )}
      </div>
      <div className="grid w-full gap-3 sm:grid-cols-2">
        {QUICK_PROMPTS.map((g) => (
          <div key={g.group} className="rounded-xl border bg-card/50 p-3">
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-muted-foreground">{g.group}</p>
            <div className="flex flex-col gap-1">
              {g.prompts.map((p) => (
                <button key={p} type="button" onClick={() => onAsk(p)} className="rounded-md px-2 py-1.5 text-left text-sm text-foreground/85 transition-colors hover:bg-accent">
                  {p}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Composer({ onSend, busy, onStop, context, clearContext }: { onSend: (t: string) => void; busy: boolean; onStop: () => void; context: string | null; clearContext: () => void }) {
  const [text, setText] = React.useState("");
  const ref = React.useRef<HTMLTextAreaElement>(null);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);
  const submit = () => {
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText("");
  };
  return (
    <div className="mx-auto w-full max-w-3xl">
      {context && (
        <div className="mb-1.5 flex items-center gap-2 rounded-md border border-info/30 bg-info/5 px-2 py-1 text-2xs text-info">
          <Paperclip className="h-3 w-3" /> Dashboard context attached ({Math.round(context.length / 100) / 10}k chars) — sent with your next question
          <button type="button" className="ml-auto" onClick={clearContext} aria-label="Remove dashboard context">
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
      <div className="relative rounded-2xl border bg-card shadow-sm focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-primary/30">
        <textarea
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, 4000))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Ask about markets, options, strategies or your portfolio…"
          aria-label="Message the copilot"
          className="block max-h-[200px] w-full resize-none bg-transparent px-4 py-3 pr-14 text-sm outline-none placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
        />
        <div className="absolute bottom-2 right-2">
          {busy ? (
            <Button size="icon-sm" variant="secondary" onClick={onStop} aria-label="Stop generating" className="rounded-full">
              <Square className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button size="icon-sm" onClick={submit} disabled={!text.trim()} aria-label="Send" className="rounded-full">
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2 px-1">
        <Disclaimer kind="ai" className="text-[10px]" />
        <span className="hidden shrink-0 text-[10px] text-muted-foreground sm:block">Enter to send · Shift+Enter for a new line</span>
      </div>
    </div>
  );
}

function Copilot() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const qc = useQueryClient();
  const ctx = usePrefs((s) => s.copilotContext);
  const setCtx = usePrefs((s) => s.setCopilotContext);
  const [sessionId, setSessionId] = React.useState<number | null>(() => (params.get("c") ? Number(params.get("c")) : null));
  const [messages, setMessages] = React.useState<ChatMessageUI[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const abortRef = React.useRef<AbortController | null>(null);
  const streamedSession = React.useRef<number | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const stick = React.useRef(true);

  // load a conversation from history (skip when we created it by streaming)
  React.useEffect(() => {
    if (sessionId === null) {
      setMessages([]);
      return;
    }
    if (streamedSession.current === sessionId) return;
    let cancel = false;
    setLoading(true);
    unwrap(api.GET("/api/ai/sessions/{session_id}", { params: { path: { session_id: sessionId } } }))
      .then((d) => !cancel && setMessages(d.messages.map((m) => fromServer(m as ServerMessage))))
      .catch(() => {
        if (!cancel) {
          setSessionId(null);
          router.replace(pathname);
        }
      })
      .finally(() => !cancel && setLoading(false));
    return () => {
      cancel = true;
    };
  }, [sessionId, pathname, router]);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const update = (fn: (m: ChatMessageUI) => ChatMessageUI) => setMessages((ms) => (ms.length ? [...ms.slice(0, -1), fn(ms[ms.length - 1]!)] : ms));

  const send = React.useCallback(
    async (text: string, context: string | null = usePrefs.getState().copilotContext) => {
      if (busy) return;
      stick.current = true;
      const assistant: ChatMessageUI = { id: `a-${Date.now()}`, role: "assistant", content: "", cards: [], citations: [], suggestions: [], tools: [], streaming: true };
      setMessages((ms) => [...ms, { id: `u-${Date.now()}`, role: "user", content: text, cards: [], citations: [], suggestions: [], tools: [] }, assistant]);
      setBusy(true);
      if (context) setCtx(null);
      const ac = new AbortController();
      abortRef.current = ac;
      const onEvent = (e: ChatEvent) => {
        switch (e.type) {
          case "start":
            streamedSession.current = e.session_id;
            setSessionId(e.session_id);
            router.replace(`${pathname}?c=${e.session_id}`, { scroll: false });
            void qc.invalidateQueries({ queryKey: ["chat-sessions"] });
            break;
          case "delta":
            update((m) => ({ ...m, content: m.content + e.text }));
            break;
          case "replace":
            update((m) => ({ ...m, content: e.text }));
            break;
          case "tool_start":
            update((m) => ({ ...m, tools: [...m.tools, { id: e.id, name: e.name, args: e.args, status: "running" }] }));
            break;
          case "tool_end":
            update((m) => ({
              ...m,
              tools: m.tools.map((t) => (t.id === e.id ? { ...t, status: e.ok ? "ok" : "error", error: e.error } : t)),
              cards: e.card ? [...m.cards, e.card] : m.cards,
            }));
            break;
          case "done":
            update((m) => ({
              ...m,
              id: e.message_id ?? m.id,
              content: e.content,
              citations: e.citations,
              suggestions: e.suggestions,
              flags: e.flags,
              model: `${e.provider}:${e.model}`,
              streaming: false,
            }));
            void qc.invalidateQueries({ queryKey: ["ai-status"] });
            break;
          case "error":
            update((m) => ({ ...m, error: e.message }));
            break;
        }
      };
      try {
        await streamChat({ message: text, session_id: sessionId, context }, onEvent, ac.signal);
      } catch (err) {
        if ((err as Error).name === "AbortError") update((m) => ({ ...m, error: "Stopped." }));
        else update((m) => ({ ...m, error: err instanceof ApiError ? err.message : "Could not reach the copilot." }));
      } finally {
        update((m) => ({ ...m, streaming: false }));
        setBusy(false);
        abortRef.current = null;
        void qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      }
    },
    [busy, sessionId, pathname, router, qc, setCtx],
  );

  // "Ask AI about this" handoff from dashboards: /?q=...
  const handled = React.useRef(false);
  React.useEffect(() => {
    const q = params.get("q");
    if (q && !handled.current) {
      handled.current = true;
      streamedSession.current = null;
      setSessionId(null);
      router.replace(pathname, { scroll: false });
      void send(q, usePrefs.getState().copilotContext);
    }
  }, [params, pathname, router, send]);

  const newChat = () => {
    abortRef.current?.abort();
    streamedSession.current = null;
    setSessionId(null);
    setMessages([]);
    setHistoryOpen(false);
    router.replace(pathname, { scroll: false });
  };
  const select = (id: number) => {
    abortRef.current?.abort();
    streamedSession.current = null;
    setSessionId(id);
    setHistoryOpen(false);
    router.replace(`${pathname}?c=${id}`, { scroll: false });
  };
  const ask = (q: string) => void send(q, null);

  return (
    <div className="-mt-1 flex h-[calc(100dvh-9.5rem)] gap-4 md:h-[calc(100dvh-6.5rem)]">
      <HistorySidebar activeId={sessionId} onSelect={select} onNew={newChat} className="hidden w-60 shrink-0 lg:flex" />
      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="h-[80vh] max-w-sm">
          <DialogTitle className="sr-only">Chat history</DialogTitle>
          <HistorySidebar activeId={sessionId} onSelect={select} onNew={newChat} className="h-full" />
        </DialogContent>
      </Dialog>
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Copilot conversation">
        <div className="mb-2 flex items-center gap-2 lg:hidden">
          <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)}>
            <History /> History
          </Button>
          <Button size="sm" variant="ghost" onClick={newChat}>
            New chat
          </Button>
        </div>
        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          className="min-h-0 flex-1 overflow-y-auto scrollbar-thin"
          role="log"
          aria-live="polite"
          aria-busy={busy}
        >
          {loading ? (
            <div className="mx-auto flex max-w-3xl flex-col gap-4 py-4">
              <Skeleton className="ml-auto h-9 w-1/2" />
              <Skeleton className="h-24" />
            </div>
          ) : messages.length === 0 ? (
            <Welcome onAsk={ask} />
          ) : (
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 py-4">
              {messages.map((m, i) => (
                <MessageView key={m.id} m={m} isLast={i === messages.length - 1} onAsk={ask} />
              ))}
            </div>
          )}
        </div>
        <div className={cn("pt-2")}>
          <Composer onSend={(t) => void send(t)} busy={busy} onStop={() => abortRef.current?.abort()} context={ctx} clearContext={() => setCtx(null)} />
        </div>
      </section>
    </div>
  );
}

export default function CopilotPage() {
  return (
    <React.Suspense>
      <Copilot />
    </React.Suspense>
  );
}
