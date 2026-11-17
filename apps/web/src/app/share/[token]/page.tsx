"use client";
import { useQuery } from "@tanstack/react-query";
import { Link2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { Disclaimer, EmptyState } from "@/components/common";
import { MessageView } from "@/components/copilot/message";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import type { Card, ChatMessageUI, Citation } from "@/lib/copilot";
import { shortDate } from "@/lib/format";

interface Shared {
  title: string;
  created_at: string;
  messages: { id: number; role: string; content: string; cards: unknown[]; citations: unknown[]; created_at: string }[];
}

export default function SharedChatPage() {
  const { token } = useParams<{ token: string }>();
  const q = useQuery({
    queryKey: ["shared-chat", token],
    queryFn: async () => {
      const r = await fetch(`/api/ai/shared/${encodeURIComponent(token)}`);
      if (!r.ok) throw new Error(r.status === 404 ? "This link is invalid or sharing was turned off." : "Could not load the conversation.");
      return (await r.json()) as Shared;
    },
    retry: false,
  });
  const msgs: ChatMessageUI[] = (q.data?.messages ?? []).map((m) => ({
    id: m.id,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    cards: m.cards as Card[],
    citations: m.citations as Citation[],
    suggestions: [],
    tools: [],
  }));
  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-3xl items-center gap-2 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-primary to-info text-xs font-bold text-white">A</div>
          <span className="text-sm font-semibold">AlgoDesk Copilot</span>
          <span className="ml-2 flex items-center gap-1 text-2xs text-muted-foreground">
            <Link2 className="h-3 w-3" /> shared, read-only
          </span>
          <Button size="sm" className="ml-auto" asChild>
            <Link href="/signup">
              <Sparkles /> Try AlgoDesk
            </Link>
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-6">
        {q.isLoading ? (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-32" />
          </div>
        ) : q.isError ? (
          <EmptyState icon={Link2} title="Conversation unavailable" description={(q.error as Error).message} />
        ) : (
          <>
            <h1 className="text-xl font-semibold tracking-tight">{q.data?.title}</h1>
            <p className="mb-6 text-xs text-muted-foreground">Shared conversation · {q.data ? shortDate(q.data.created_at) : ""}</p>
            <div className="flex flex-col gap-5">
              {msgs.map((m) => (
                <MessageView key={m.id} m={m} readOnly />
              ))}
            </div>
            <Disclaimer kind="ai" className="mt-8" />
          </>
        )}
      </main>
    </div>
  );
}
