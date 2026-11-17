"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Link2Off, MessageSquare, MoreHorizontal, Pencil, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { api, unwrap } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

export function HistorySidebar({ activeId, onSelect, onNew, className }: { activeId: number | null; onSelect: (id: number) => void; onNew: () => void; className?: string }) {
  const qc = useQueryClient();
  const [q, setQ] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [renaming, setRenaming] = React.useState<number | null>(null);
  const [title, setTitle] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const sessions = useQuery({
    queryKey: ["chat-sessions", debounced],
    queryFn: () => unwrap(api.GET("/api/ai/sessions", { params: { query: { q: debounced || undefined, limit: 100 } } })),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["chat-sessions"] });
  const patch = useMutation({
    mutationFn: (v: { id: number; title?: string; pinned?: boolean }) =>
      unwrap(api.PATCH("/api/ai/sessions/{session_id}", { params: { path: { session_id: v.id } }, body: { title: v.title ?? null, pinned: v.pinned ?? null } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/api/ai/sessions/{session_id}", { params: { path: { session_id: id } } })),
    onSuccess: (_, id) => {
      refresh();
      if (id === activeId) onNew();
    },
  });
  const share = async (id: number, shared: boolean) => {
    try {
      if (shared) {
        await unwrap(api.DELETE("/api/ai/sessions/{session_id}/share", { params: { path: { session_id: id } } }));
        toast.success("Sharing disabled — the link no longer works");
      } else {
        const r = await unwrap(api.POST("/api/ai/sessions/{session_id}/share", { params: { path: { session_id: id } } }));
        const url = `${window.location.origin}${r.path}`;
        await navigator.clipboard?.writeText(url).catch(() => undefined);
        toast.success("Read-only link copied", { description: url });
      }
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const rows = sessions.data ?? [];
  const pinned = rows.filter((s) => s.pinned);
  const recent = rows.filter((s) => !s.pinned);
  const item = (s: (typeof rows)[number]) => (
    <li key={s.id} className="group relative">
      {renaming === s.id ? (
        <form
          className="px-1 py-0.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) patch.mutate({ id: s.id, title: title.trim() });
            setRenaming(null);
          }}
        >
          <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => setRenaming(null)} className="h-7 text-xs" aria-label="Chat title" />
        </form>
      ) : (
        <button
          type="button"
          onClick={() => onSelect(s.id)}
          className={cn(
            "flex w-full flex-col items-start rounded-md px-2 py-1.5 pr-8 text-left transition-colors",
            s.id === activeId ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
          )}
          aria-current={s.id === activeId ? "page" : undefined}
        >
          <span className="flex w-full items-center gap-1 truncate text-xs font-medium">
            {s.shared && <Link2 className="h-3 w-3 shrink-0 text-info" aria-label="shared" />}
            <span className="truncate">{s.title}</span>
          </span>
          <span className="text-2xs text-muted-foreground">{timeAgo(s.updated_at)}</span>
        </button>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" className="absolute right-0.5 top-1 h-7 w-7 opacity-0 focus:opacity-100 group-hover:opacity-100" aria-label={`Actions for ${s.title}`}>
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem
            onSelect={() => {
              setTitle(s.title);
              setRenaming(s.id);
            }}
          >
            <Pencil className="h-3.5 w-3.5" /> Rename
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => patch.mutate({ id: s.id, pinned: !s.pinned })}>
            {s.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />} {s.pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void share(s.id, s.shared)}>
            {s.shared ? <Link2Off className="h-3.5 w-3.5" /> : <Link2 className="h-3.5 w-3.5" />} {s.shared ? "Stop sharing" : "Share read-only link"}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-loss focus:text-loss" onSelect={() => confirm(`Delete "${s.title}"?`) && remove.mutate(s.id)}>
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
  return (
    <aside className={cn("flex min-h-0 flex-col gap-2", className)} aria-label="Chat history">
      <Button onClick={onNew} className="justify-start" size="sm">
        <Plus /> New chat
      </Button>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chats" className="h-8 pl-7 text-xs" aria-label="Search chats" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin">
        {sessions.isLoading ? (
          <div className="flex flex-col gap-1.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="flex items-center gap-1.5 px-2 py-4 text-xs text-muted-foreground">
            <MessageSquare className="h-3.5 w-3.5" /> {debounced ? "No matching chats" : "No chats yet"}
          </p>
        ) : (
          <>
            {pinned.length > 0 && (
              <>
                <p className="px-2 pb-1 pt-1 text-2xs font-semibold uppercase tracking-wider text-muted-foreground">Pinned</p>
                <ul className="mb-2 flex flex-col gap-0.5">{pinned.map(item)}</ul>
              </>
            )}
            <p className="px-2 pb-1 pt-1 text-2xs font-semibold uppercase tracking-wider text-muted-foreground">Recent</p>
            <ul className="flex flex-col gap-0.5">{recent.map(item)}</ul>
          </>
        )}
      </div>
    </aside>
  );
}
