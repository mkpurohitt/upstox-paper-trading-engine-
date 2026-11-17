"use client";
import { motion } from "framer-motion";
import { AlertCircle, Check, CheckCircle2, Copy, FileText, Loader2, Sparkles, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";
import dynamic from "next/dynamic";
import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger, Skeleton } from "@/components/ui/misc";
import { Tooltip } from "@/components/ui/tooltip";
import { apiJson } from "@/lib/api";
import { type ChatMessageUI, type Citation, toolLabel } from "@/lib/copilot";
import { cn } from "@/lib/utils";

// cards pull in charting libraries; load them only when a message actually has cards
const CopilotCard = dynamic(() => import("@/components/copilot/cards").then((m) => m.CopilotCard), {
  ssr: false,
  loading: () => <Skeleton className="h-40" />,
});

function CitationChip({ n, cite }: { n: number; cite?: Citation }) {
  if (!cite) return <sup className="text-2xs text-muted-foreground">[{n}]</sup>;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/15 px-1 align-text-top text-[10px] font-semibold text-primary hover:bg-primary/25"
          aria-label={`Source ${n}: ${cite.title}`}
        >
          {n}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 text-xs">
        <p className="font-semibold">{cite.title}</p>
        {cite.heading ? <p className="text-2xs text-muted-foreground">{cite.heading.split(" › ").slice(1).join(" › ")}</p> : null}
        <p className="mt-2 leading-relaxed text-muted-foreground">“{cite.snippet}”</p>
        {cite.source_url ? (
          <a href={cite.source_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-primary underline">
            Open source
          </a>
        ) : (
          <p className="mt-2 text-2xs text-muted-foreground">AlgoDesk knowledge base · {cite.source_type}</p>
        )}
      </PopoverContent>
    </Popover>
  );
}

function md(citations: Citation[]): Components {
  const byN = new Map(citations.map((c) => [c.n, c]));
  return {
    p: ({ children }) => <p className="my-1.5 leading-relaxed">{children}</p>,
    ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
    ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
    h1: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold">{children}</h3>,
    h2: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold">{children}</h3>,
    h3: ({ children }) => <h4 className="mb-1 mt-2 text-sm font-semibold">{children}</h4>,
    code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>,
    pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-md bg-muted/60 p-2 text-xs scrollbar-thin">{children}</pre>,
    table: ({ children }) => (
      <div className="my-2 overflow-x-auto scrollbar-thin">
        <table className="num w-auto border-collapse text-xs">{children}</table>
      </div>
    ),
    th: ({ children }) => <th className="border-b px-2 py-1 text-left font-medium text-muted-foreground">{children}</th>,
    td: ({ children }) => <td className="border-b border-border/50 px-2 py-1">{children}</td>,
    a: ({ href, children }) => {
      if (href?.startsWith("#cite-")) {
        const n = Number(href.slice(6));
        return <CitationChip n={n} cite={byN.get(n)} />;
      }
      const external = href?.startsWith("http");
      return (
        <a href={href} className="text-primary underline underline-offset-2" {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
          {children}
        </a>
      );
    },
  };
}

/** Turn "[n]" markers (not already links) into citation links rendered as chips. */
export function withCitationLinks(text: string): string {
  return text.replace(/\[(\d{1,2})\](?!\()/g, "[$1](#cite-$1)");
}

function ToolChips({ tools }: { tools: ChatMessageUI["tools"] }) {
  if (!tools.length) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-1.5" aria-live="polite">
      {tools.map((t) => (
        <span
          key={t.id}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs",
            t.status === "running" && "border-primary/40 text-primary",
            t.status === "ok" && "text-muted-foreground",
            t.status === "error" && "border-loss/40 text-loss",
          )}
          title={t.error ?? undefined}
        >
          {t.status === "running" ? <Loader2 className="h-3 w-3 animate-spin" /> : t.status === "ok" ? <CheckCircle2 className="h-3 w-3 text-profit" /> : <AlertCircle className="h-3 w-3" />}
          {toolLabel(t.name)}
        </span>
      ))}
    </div>
  );
}

function Feedback({ id }: { id: number }) {
  const [given, setGiven] = React.useState<"up" | "down" | null>(null);
  const send = async (rating: "up" | "down") => {
    setGiven(rating);
    try {
      await apiJson(`/api/ai/messages/${id}/feedback`, { method: "POST", body: JSON.stringify({ rating }) });
      toast.success("Thanks for the feedback");
    } catch {
      setGiven(null);
    }
  };
  return (
    <>
      <Tooltip content="Helpful">
        <Button size="icon-sm" variant="ghost" className={cn("h-7 w-7", given === "up" && "text-profit")} onClick={() => send("up")} disabled={!!given} aria-label="Helpful">
          <ThumbsUp className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <Tooltip content="Not helpful">
        <Button size="icon-sm" variant="ghost" className={cn("h-7 w-7", given === "down" && "text-loss")} onClick={() => send("down")} disabled={!!given} aria-label="Not helpful">
          <ThumbsDown className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
    </>
  );
}

export function MessageView({
  m,
  isLast,
  onAsk,
  readOnly = false,
}: {
  m: ChatMessageUI;
  isLast?: boolean;
  onAsk?: (q: string) => void;
  readOnly?: boolean;
}) {
  const [copied, setCopied] = React.useState(false);
  const components = React.useMemo(() => md(m.citations), [m.citations]);
  if (m.role === "user") {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground">{m.content}</div>
      </motion.div>
    );
  }
  const blocked = m.flags?.includes("blocked");
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="group flex gap-3">
      <div className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", blocked ? "bg-warning/15 text-warning" : "bg-gradient-to-br from-primary to-info text-white")}>
        {blocked ? <AlertCircle className="h-4 w-4" /> : <Sparkles className="h-3.5 w-3.5" />}
      </div>
      <div className="min-w-0 flex-1">
        <ToolChips tools={m.tools} />
        {m.content ? (
          <div className="text-sm text-foreground/90">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
              {withCitationLinks(m.content)}
            </ReactMarkdown>
            {m.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary align-text-bottom" aria-hidden />}
          </div>
        ) : m.streaming && !m.tools.length ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Thinking…
          </div>
        ) : null}
        {m.error && (
          <p className="mt-1 flex items-center gap-1 text-xs text-loss">
            <AlertCircle className="h-3.5 w-3.5" /> {m.error}
          </p>
        )}
        {m.cards.length > 0 && (
          <div className="mt-2 flex flex-col gap-2">
            {m.cards.map((c, i) => (
              <CopilotCard key={i} card={c} onAsk={readOnly ? undefined : onAsk} />
            ))}
          </div>
        )}
        {m.citations.length > 0 && !m.streaming && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-2xs text-muted-foreground">
            <FileText className="h-3 w-3" /> Sources:
            {m.citations.map((c) => (
              <span key={c.n} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5">
                <span className="font-semibold text-primary">{c.n}</span> {c.title}
              </span>
            ))}
          </div>
        )}
        {!m.streaming && (
          <div className="mt-1 flex items-center gap-0.5 opacity-70 transition-opacity group-hover:opacity-100">
            <Tooltip content={copied ? "Copied" : "Copy"}>
              <Button
                size="icon-sm"
                variant="ghost"
                className="h-7 w-7"
                aria-label="Copy answer"
                onClick={() => {
                  void navigator.clipboard?.writeText(m.content);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </Tooltip>
            {!readOnly && typeof m.id === "number" && <Feedback id={m.id} />}
            {m.model && (
              <span className="ml-1 flex items-center gap-1 text-2xs text-muted-foreground">
                <Wrench className="h-3 w-3" /> {m.model.replace("mock:algodesk-offline-1", "offline assistant")}
              </span>
            )}
          </div>
        )}
        {isLast && !readOnly && !m.streaming && m.suggestions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {m.suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onAsk?.(s)}
                className="rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
