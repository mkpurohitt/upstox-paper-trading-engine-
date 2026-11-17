"use client";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, ExternalLink, Loader2, Newspaper, Search, Sparkles, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Disclaimer, EmptyState, PageHeader } from "@/components/common";
import { useAskAI } from "@/components/dashboard";
import { SymbolSearch } from "@/components/symbol-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiJson } from "@/lib/api";
import { num, shortDate, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Item { id: number; source: string; url: string; title: string; summary: string; ai_summary: string | null; category: string; published_at: string; sentiment: string; sentiment_score: number; tickers: string[] }
interface Senti { hours: number; articles: number; counts: Record<string, number>; net_score: number; tickers: { symbol: string; mentions: number; avg_score: number }[] }
interface Cal { economic: { date: string; title: string; country: string; impact: string }[]; results: Record<string, string>[]; corporate_actions: Record<string, string>[]; note: string }

const SENT: Record<string, "profit" | "loss" | "secondary"> = { positive: "profit", negative: "loss", neutral: "secondary" };
const short = (s: string) => s.split(":").pop() ?? s;

function Article({ n }: { n: Item }) {
  const qc = useQueryClient();
  const ask = useAskAI();
  const [ai, setAi] = React.useState(n.ai_summary);
  const sum = useMutation({
    mutationFn: () => apiJson<Item>(`/api/news/${n.id}/summarize`, { method: "POST" }),
    onSuccess: (r) => {
      setAi(r.ai_summary);
      void qc.invalidateQueries({ queryKey: ["news-sentiment"] });
    },
  });
  const real = !n.url.includes(".invalid");
  return (
    <article className="flex flex-col gap-1.5 border-b px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-1.5 text-2xs text-muted-foreground">
        <Badge variant={SENT[n.sentiment] ?? "secondary"} className="capitalize">
          {n.sentiment}
        </Badge>
        {n.category !== "news" && <Badge variant="outline" className="capitalize">{n.category}</Badge>}
        <span>{n.source}</span>·<time dateTime={n.published_at}>{timeAgo(n.published_at)}</time>
      </div>
      <h3 className="text-sm font-medium leading-snug">
        {real ? (
          <a href={n.url} target="_blank" rel="noopener noreferrer" className="hover:text-primary">
            {n.title} <ExternalLink className="inline h-3 w-3 text-muted-foreground" />
          </a>
        ) : (
          n.title
        )}
      </h3>
      {ai ? (
        <p className="rounded-md border-l-2 border-primary/60 bg-primary/5 px-2 py-1 text-xs text-foreground/85">
          <Sparkles className="mr-1 inline h-3 w-3 text-primary" />
          {ai}
        </p>
      ) : n.summary && !n.summary.includes("Sample headline") ? (
        <p className="line-clamp-2 text-xs text-muted-foreground">{n.summary}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-1.5">
        {n.tickers.slice(0, 5).map((t) => (
          <Link key={t} href={`/analysis/technical?symbol=${encodeURIComponent(t)}`} className="rounded border px-1.5 py-0.5 font-mono text-[10px] hover:border-primary/60 hover:text-primary">
            {short(t)}
          </Link>
        ))}
        <span className="ml-auto flex gap-1">
          {!ai && (
            <Button size="xs" variant="ghost" onClick={() => sum.mutate()} disabled={sum.isPending}>
              {sum.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />} Summarise
            </Button>
          )}
          <Button size="xs" variant="ghost" onClick={() => ask(`What does this news mean for ${n.tickers.map(short).join(", ") || "the market"}?`, { title: n.title, summary: ai ?? n.summary, source: n.source, published_at: n.published_at, tickers: n.tickers })}>
            Ask AI
          </Button>
        </span>
      </div>
    </article>
  );
}

function SentimentCard() {
  const q = useQuery({ queryKey: ["news-sentiment"], queryFn: () => apiJson<Senti>("/api/news/sentiment?hours=48"), refetchInterval: 120_000 });
  const d = q.data;
  if (!d) return <Skeleton className="h-48" />;
  const total = d.articles || 1;
  const bar = (k: string, cls: string) => <span className={cls} style={{ width: `${((d.counts[k] ?? 0) / total) * 100}%` }} />;
  return (
    <Card>
      <CardHeader>
        <CardTitle>News sentiment · 48h</CardTitle>
        <CardDescription>
          {d.articles} articles · net {d.net_score > 0 ? "+" : ""}
          {num(d.net_score * 100, 0)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`positive ${d.counts.positive}, neutral ${d.counts.neutral}, negative ${d.counts.negative}`}>
          {bar("positive", "bg-profit")}
          {bar("neutral", "bg-muted-foreground/40")}
          {bar("negative", "bg-loss")}
        </div>
        <div className="flex justify-between text-2xs text-muted-foreground">
          <span className="text-profit">▲ {d.counts.positive} positive</span>
          <span>{d.counts.neutral} neutral</span>
          <span className="text-loss">▼ {d.counts.negative} negative</span>
        </div>
        <div className="flex flex-col gap-1">
          <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">Most mentioned</p>
          {d.tickers.slice(0, 8).map((t) => (
            <Link key={t.symbol} href={`/analysis/technical?symbol=${encodeURIComponent(t.symbol)}`} className="flex items-center justify-between rounded px-1 py-0.5 text-xs hover:bg-accent">
              <span className="font-medium">{short(t.symbol)}</span>
              <span className="flex items-center gap-2 text-2xs">
                <span className="text-muted-foreground">{t.mentions}×</span>
                <span className={cn("num w-10 text-right", t.avg_score > 0.1 ? "text-profit" : t.avg_score < -0.1 ? "text-loss" : "text-muted-foreground")}>
                  {t.avg_score > 0 ? "+" : ""}
                  {num(t.avg_score, 2)}
                </span>
              </span>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function CalendarCard() {
  const q = useQuery({ queryKey: ["news-calendar"], queryFn: () => apiJson<Cal>("/api/news/calendar?days=30"), staleTime: 600_000 });
  const [tab, setTab] = React.useState<"economic" | "results" | "actions">("economic");
  const d = q.data;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <CalendarDays className="h-4 w-4 text-primary" /> Calendar
        </CardTitle>
        <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
          <TabsList className="w-full">
            <TabsTrigger value="economic" className="flex-1">Economy</TabsTrigger>
            <TabsTrigger value="results" className="flex-1">Results</TabsTrigger>
            <TabsTrigger value="actions" className="flex-1">Corp. actions</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="max-h-[420px] overflow-y-auto scrollbar-thin">
        {!d ? (
          <Skeleton className="h-40" />
        ) : tab === "economic" ? (
          <>
            <ul className="flex flex-col gap-1.5">
              {d.economic.map((e, i) => (
                <li key={i} className="flex items-center gap-2 text-xs">
                  <span className="num w-14 shrink-0 text-muted-foreground">{shortDate(e.date)}</span>
                  <span className={cn("h-2 w-2 shrink-0 rounded-full", e.impact === "high" ? "bg-loss" : "bg-warning")} aria-label={`${e.impact} impact`} />
                  <span className="flex-1">{e.title}</span>
                  <Badge variant="outline" className="text-[10px]">{e.country}</Badge>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[10px] text-muted-foreground">{d.note}</p>
          </>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {(tab === "results" ? d.results : d.corporate_actions).map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span className="num w-14 shrink-0 text-muted-foreground">{shortDate(r.date ?? r.meeting_date ?? r.ex_date ?? "")}</span>
                <Link href={`/analysis/fundamental?symbol=NSE:${r.symbol}`} className="w-20 shrink-0 font-medium hover:text-primary">
                  {r.symbol}
                </Link>
                <span className="flex-1 text-muted-foreground">{r.purpose ?? r.subject ?? "Board meeting"}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function NewsPage() {
  const [category, setCategory] = React.useState("all");
  const [sentiment, setSentiment] = React.useState("all");
  const [symbol, setSymbol] = React.useState<string | null>(null);
  const [q, setQ] = React.useState("");
  const [query, setQuery] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  const params = (before?: string) => {
    const p = new URLSearchParams({ limit: "30" });
    if (category !== "all") p.set("category", category);
    if (sentiment !== "all") p.set("sentiment", sentiment);
    if (symbol) p.set("symbol", symbol);
    if (query) p.set("q", query);
    if (before) p.set("before", before);
    return p.toString();
  };
  const feed = useInfiniteQuery({
    queryKey: ["news", category, sentiment, symbol, query],
    queryFn: ({ pageParam }) => apiJson<Item[]>(`/api/news?${params(pageParam)}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.length === 30 ? last[last.length - 1]?.published_at : undefined),
    refetchInterval: 120_000,
  });
  const items = feed.data?.pages.flat() ?? [];
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader icon={Newspaper} title="News" description="Market news with AI summaries and sentiment, exchange filings and the event calendar" />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-3 lg:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={category} onValueChange={setCategory}>
              <TabsList>
                <TabsTrigger value="all">All</TabsTrigger>
                <TabsTrigger value="news">News</TabsTrigger>
                <TabsTrigger value="announcement">Filings</TabsTrigger>
                <TabsTrigger value="economy">Economy</TabsTrigger>
              </TabsList>
            </Tabs>
            <Select value={sentiment} onValueChange={setSentiment} className="h-8 w-36 text-xs" ariaLabel="Sentiment" options={[{ value: "all", label: "Any sentiment" }, { value: "positive", label: "Positive" }, { value: "negative", label: "Negative" }, { value: "neutral", label: "Neutral" }]} />
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search headlines" className="h-8 w-44 pl-7 text-xs" aria-label="Search headlines" />
            </div>
            {symbol ? (
              <Badge variant="info" className="h-8 gap-1 px-2">
                {short(symbol)}
                <button type="button" onClick={() => setSymbol(null)} aria-label="Clear symbol filter">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ) : (
              <SymbolSearch onPick={setSymbol} placeholder="Filter by stock…" className="w-44" filter={(h) => h.instrument_type === "EQ"} />
            )}
          </div>
          <Card>
            <CardContent className="p-0">
              {feed.isLoading ? (
                <div className="flex flex-col gap-3 p-4">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <Skeleton key={i} className="h-16" />
                  ))}
                </div>
              ) : items.length === 0 ? (
                <EmptyState className="m-4" icon={Newspaper} title="No articles match" description="Try another filter." />
              ) : (
                items.map((n) => <Article key={n.id} n={n} />)
              )}
            </CardContent>
          </Card>
          {feed.hasNextPage && (
            <Button variant="outline" onClick={() => void feed.fetchNextPage()} loading={feed.isFetchingNextPage} className="self-center">
              Load older
            </Button>
          )}
          <Disclaimer kind="ai" />
        </div>
        <div className="flex flex-col gap-3">
          <SentimentCard />
          <CalendarCard />
        </div>
      </div>
    </div>
  );
}
