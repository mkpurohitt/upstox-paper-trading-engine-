"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Globe, RefreshCw, Search, Trash2, Type, Upload } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Field } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiFetch, apiJson, ApiError } from "@/lib/api";
import { shortDate } from "@/lib/format";

interface Doc { id: number; title: string; source_type: string; source_url: string | null; mime: string; status: string; chunk_count: number; error: string | null; created_at: string; indexed_at: string | null }
interface Chunk { id: number; ordinal: number; token_count: number; content: string; meta: Record<string, unknown> }
interface Hit { n: number; title: string; heading: string | null; snippet: string; score: number; source_type: string }

export function RagManager() {
  const qc = useQueryClient();
  const docs = useQuery({ queryKey: ["rag-docs"], queryFn: () => apiJson<Doc[]>("/api/rag/documents") });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["rag-docs"] });
  const [file, setFile] = React.useState<File | null>(null);
  const [url, setUrl] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [text, setText] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<Hit[] | null>(null);
  const [viewing, setViewing] = React.useState<Doc | null>(null);
  const chunks = useQuery({ queryKey: ["rag-chunks", viewing?.id], queryFn: () => apiJson<Chunk[]>(`/api/rag/documents/${viewing!.id}/chunks`), enabled: !!viewing });
  const ok = (m: string) => {
    toast.success(m);
    refresh();
  };
  const err = (e: Error) => toast.error(e instanceof ApiError ? e.message : "Request failed");
  const upload = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("file", file!);
      if (title) fd.append("title", title);
      const r = await apiFetch("/api/rag/documents/upload", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new ApiError(j?.error?.message ?? j?.detail ?? "Upload failed", r.status);
      return j as Doc;
    },
    onSuccess: (d) => {
      setFile(null);
      setTitle("");
      ok(`Indexed "${d.title}" (${d.chunk_count} chunks)`);
    },
    onError: err,
  });
  const addUrl = useMutation({
    mutationFn: () => apiJson<Doc>("/api/rag/documents/url", { method: "POST", body: JSON.stringify({ url, title: title || null }) }),
    onSuccess: (d) => {
      setUrl("");
      ok(`Indexed "${d.title}" (${d.chunk_count} chunks)`);
    },
    onError: err,
  });
  const addText = useMutation({
    mutationFn: () => apiJson<Doc>("/api/rag/documents/text", { method: "POST", body: JSON.stringify({ title, text }) }),
    onSuccess: (d) => {
      setText("");
      setTitle("");
      ok(`Indexed "${d.title}" (${d.chunk_count} chunks)`);
    },
    onError: err,
  });
  const act = useMutation({
    mutationFn: ({ id, what }: { id: number; what: "reindex" | "delete" }) =>
      apiJson(what === "delete" ? `/api/rag/documents/${id}` : `/api/rag/documents/${id}/reindex`, { method: what === "delete" ? "DELETE" : "POST" }),
    onSuccess: (_, v) => ok(v.what === "delete" ? "Document deleted" : "Re-indexed"),
    onError: err,
  });
  const reindexAll = useMutation({ mutationFn: () => apiJson("/api/rag/reindex-all", { method: "POST" }), onSuccess: () => ok("Re-indexing queued"), onError: err });
  const search = useMutation({
    mutationFn: () => apiJson<Hit[]>("/api/rag/search", { method: "POST", body: JSON.stringify({ query, k: 5 }) }),
    onSuccess: setHits,
    onError: err,
  });
  const rows = docs.data ?? [];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Add knowledge</CardTitle>
            <CardDescription>PDF, HTML, Markdown or text. Documents are chunked by heading (~800 tokens), embedded and searchable by the copilot immediately.</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="file">
              <TabsList>
                <TabsTrigger value="file">
                  <Upload /> File
                </TabsTrigger>
                <TabsTrigger value="url">
                  <Globe /> URL
                </TabsTrigger>
                <TabsTrigger value="text">
                  <Type /> Text
                </TabsTrigger>
              </TabsList>
              <div className="mt-3">
                <Field label="Title (optional for file/URL)">
                  <Input value={title} onChange={(e) => setTitle(e.target.value)} />
                </Field>
              </div>
              <TabsContent value="file" className="flex flex-col gap-2">
                <input type="file" accept=".pdf,.md,.markdown,.txt,.html,.htm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs file:mr-3 file:rounded-md file:border file:bg-muted file:px-3 file:py-1.5 file:text-xs" aria-label="Choose a file" />
                <Button disabled={!file} loading={upload.isPending} onClick={() => upload.mutate()} className="self-start">
                  <Upload /> Upload & index
                </Button>
              </TabsContent>
              <TabsContent value="url" className="flex flex-col gap-2">
                <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.sebi.gov.in/legal/circulars/…" />
                <Button disabled={!/^https?:\/\//.test(url)} loading={addUrl.isPending} onClick={() => addUrl.mutate()} className="self-start">
                  <Globe /> Fetch & index
                </Button>
              </TabsContent>
              <TabsContent value="text" className="flex flex-col gap-2">
                <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder="# Heading&#10;&#10;Paste markdown or plain text…" className="w-full rounded-md border bg-transparent p-2 font-mono text-xs" aria-label="Document text" />
                <Button disabled={!title || text.length < 20} loading={addText.isPending} onClick={() => addText.mutate()} className="self-start">
                  <FileText /> Index text
                </Button>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Test retrieval</CardTitle>
            <CardDescription>Hybrid search (vectors + BM25, fused and reranked) exactly as the copilot sees it.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (query.trim().length > 1) search.mutate();
              }}
            >
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. What is the STT on options?" />
              <Button type="submit" loading={search.isPending}>
                <Search />
              </Button>
            </form>
            {hits && hits.length === 0 && <p className="text-xs text-muted-foreground">No relevant chunks (below the relevance gate).</p>}
            {hits?.map((h) => (
              <div key={h.n} className="rounded-md border p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-primary">[{h.n}]</span>
                  <span className="font-medium">{h.title}</span>
                  <span className="num ml-auto text-2xs text-muted-foreground">score {h.score.toFixed(3)}</span>
                </div>
                {h.heading ? <p className="text-2xs text-muted-foreground">{h.heading}</p> : null}
                <p className="mt-1 text-muted-foreground">{h.snippet}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Documents ({rows.length})</CardTitle>
            <CardDescription>{rows.reduce((a, d) => a + d.chunk_count, 0)} chunks indexed</CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => confirm("Re-index every document? (needed after changing the embedding provider)") && reindexAll.mutate()}>
            <RefreshCw /> Re-index all
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {docs.isLoading ? (
            <Skeleton className="m-4 h-40" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Title</TH>
                  <TH>Source</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Chunks</TH>
                  <TH>Indexed</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {rows.map((d) => (
                  <TR key={d.id}>
                    <TD>
                      <button type="button" className="text-left text-xs font-medium hover:text-primary" onClick={() => setViewing(d)}>
                        {d.title}
                      </button>
                      {d.source_url ? <div className="max-w-xs truncate text-2xs text-muted-foreground">{d.source_url}</div> : null}
                    </TD>
                    <TD>
                      <Badge variant="outline">{d.source_type}</Badge>
                    </TD>
                    <TD>
                      <Badge variant={d.status === "ready" ? "profit" : d.status === "error" ? "loss" : "info"} title={d.error ?? undefined}>
                        {d.status}
                      </Badge>
                    </TD>
                    <TD className="num text-right">{d.chunk_count}</TD>
                    <TD className="text-xs text-muted-foreground">{d.indexed_at ? shortDate(d.indexed_at) : "—"}</TD>
                    <TD className="text-right">
                      <Button size="icon-sm" variant="ghost" aria-label={`Re-index ${d.title}`} onClick={() => act.mutate({ id: d.id, what: "reindex" })}>
                        <RefreshCw className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="icon-sm" variant="ghost" aria-label={`Delete ${d.title}`} onClick={() => confirm(`Delete "${d.title}"?`) && act.mutate({ id: d.id, what: "delete" })}>
                        <Trash2 className="h-3.5 w-3.5 text-loss" />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <Dialog open={!!viewing} onOpenChange={(o) => !o && setViewing(null)}>
        <DialogContent wide>
          <DialogHeader>
            <DialogTitle>{viewing?.title}</DialogTitle>
            <DialogDescription>
              {viewing?.chunk_count} chunks · {viewing?.mime}
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto scrollbar-thin">
            {chunks.isLoading && <Skeleton className="h-40" />}
            {chunks.data?.map((c) => (
              <div key={c.id} className="rounded-md border p-2">
                <div className="mb-1 flex gap-2 text-2xs text-muted-foreground">
                  <span>#{c.ordinal}</span>
                  <span>{c.token_count} tokens</span>
                  <span className="truncate">{String(c.meta.heading ?? "")}</span>
                </div>
                <pre className="whitespace-pre-wrap font-sans text-xs">{c.content.split("\n").slice(1).join("\n")}</pre>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
