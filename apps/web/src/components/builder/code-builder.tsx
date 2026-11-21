"use client";
import Editor, { type BeforeMount, loader } from "@monaco-editor/react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, Play, RotateCcw, ShieldCheck, XCircle } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { api, unwrap } from "@/lib/api";
import { useBuilder } from "@/lib/builder-store";
import type { DSL } from "@/lib/dsl";

// Monaco is served from /monaco/vs (copied from the installed monaco-editor package by scripts/copy-monaco.mjs), so
// the editor works offline and behind firewalls instead of depending on a CDN.
loader.config({ paths: { vs: "/monaco/vs" } });

/** Monaco when it loads; a plain monospace textarea otherwise (offline, blocked assets), so editing always works. */
function CodeEditor({
  value,
  onChange,
  language,
  height = 560,
  beforeMount,
}: {
  value: string;
  onChange: (v: string) => void;
  language: "python" | "json";
  height?: number;
  beforeMount?: BeforeMount;
}) {
  const { resolvedTheme } = useTheme();
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    const t = setTimeout(() => alive && setFailed(true), 20_000); // never leave the user staring at a spinner
    loader
      .init()
      .then(() => clearTimeout(t))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);
  if (failed) {
    return (
      <div className="flex flex-col">
        <p className="flex items-center gap-1.5 border-b bg-warning/10 px-3 py-1.5 text-2xs text-muted-foreground">
          <AlertTriangle className="h-3 w-3 text-warning" /> The rich editor could not load; using the basic editor (everything still works).
        </p>
        <textarea
          aria-label={language === "json" ? "Strategy JSON" : "Strategy code"}
          spellCheck={false}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{ height }}
          className="w-full resize-y bg-background p-3 font-mono text-xs leading-relaxed outline-none"
        />
      </div>
    );
  }
  return (
    <Editor
      height={`${height}px`}
      language={language}
      theme={resolvedTheme === "light" ? "light" : "vs-dark"}
      value={value}
      beforeMount={beforeMount}
      onChange={(v) => onChange(v ?? "")}
      loading={<Skeleton className="h-full w-full rounded-none" />}
      options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, tabSize: language === "json" ? 2 : 4, wordWrap: "on", fontFamily: "var(--font-geist-mono)" }}
    />
  );
}

export function CodeBuilder() {
  const code = useBuilder((s) => s.code);
  const setCode = useBuilder((s) => s.setCode);
  const setDsl = useBuilder((s) => s.setDsl);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<{ ok: boolean; errors: { path?: string; message?: string }[]; stdout: string } | null>(null);
  const tpl = useQuery({ queryKey: ["code-template"], queryFn: () => unwrap(api.GET("/api/strategies/code-template")), staleTime: Infinity, enabled: code === null });
  React.useEffect(() => {
    if (code === null && tpl.data?.code) useBuilder.setState({ code: tpl.data.code });
  }, [code, tpl.data]);

  const compile = async () => {
    setBusy(true);
    try {
      const r = await unwrap(api.POST("/api/strategies/compile-code", { body: { code: code ?? "" } }));
      setResult({ ok: r.ok, errors: (r.errors ?? []) as { path?: string; message?: string }[], stdout: r.stdout ?? "" });
      if (r.ok && r.dsl) {
        setDsl(r.dsl as DSL);
        toast.success("Compiled to DSL — form, visual and backtest now use this version");
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-2 text-xs">
        <ShieldCheck className="h-4 w-4 text-profit" />
        <span className="text-muted-foreground">Sandboxed Python: no imports, no file/network I/O, CPU & memory limited. Compiles to the same DSL as the other builders.</span>
        <Button size="sm" className="ml-auto" onClick={compile} loading={busy}>
          <Play /> Compile
        </Button>
      </div>
      <div className="overflow-hidden rounded-lg border">
        {code === null ? (
          <Skeleton className="h-[560px] rounded-none" />
        ) : (
          <CodeEditor language="python" value={code} onChange={setCode} />
        )}
      </div>
      {result && (
        <div className="rounded-lg border bg-card p-3 text-xs">
          {result.ok ? (
            <p className="flex items-center gap-1.5 text-profit">
              <CheckCircle2 className="h-4 w-4" /> Compiled successfully
            </p>
          ) : (
            <ul className="space-y-1">
              {result.errors.map((e, i) => (
                <li key={i} className="flex items-start gap-1.5 text-loss">
                  <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {e.path && <Badge variant="loss">{e.path}</Badge>} {e.message}
                </li>
              ))}
            </ul>
          )}
          {result.stdout && <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted p-2 font-mono text-2xs">{result.stdout}</pre>}
        </div>
      )}
    </div>
  );
}

export function JsonView() {
  const dsl = useBuilder((s) => s.dsl);
  const setDsl = useBuilder((s) => s.setDsl);
  const errors = useBuilder((s) => s.errors);
  const pretty = React.useMemo(() => JSON.stringify(dsl, null, 2), [dsl]);
  const [text, setText] = React.useState(pretty);
  const [edited, setEdited] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [problems, setProblems] = React.useState<{ path?: string; message?: string }[]>([]);
  const schema = useQuery({ queryKey: ["dsl-schema"], queryFn: () => unwrap(api.GET("/api/strategies/dsl/schema")), staleTime: Infinity });

  // follow changes made in the other builders unless the user is mid-edit here
  React.useEffect(() => {
    if (!edited) setText(pretty);
  }, [pretty, edited]);

  const beforeMount: BeforeMount = React.useCallback(
    (monaco) => {
      const m = monaco as unknown as {
        languages?: { json?: { jsonDefaults?: { setDiagnosticsOptions: (o: unknown) => void } } };
        json?: { jsonDefaults?: { setDiagnosticsOptions: (o: unknown) => void } };
      };
      const defaults = m.languages?.json?.jsonDefaults ?? m.json?.jsonDefaults;
      if (defaults && schema.data) {
        defaults.setDiagnosticsOptions({ validate: true, allowComments: false, schemas: [{ uri: "https://algodesk.local/dsl.schema.json", fileMatch: ["*"], schema: schema.data }] });
      }
    },
    [schema.data],
  );

  const apply = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setProblems([{ path: "JSON", message: (e as Error).message }]);
      return;
    }
    setBusy(true);
    try {
      const r = await unwrap(api.POST("/api/strategies/validate", { body: parsed as Record<string, never> }));
      if (r.valid && r.dsl) {
        setDsl(r.dsl as unknown as DSL);
        setProblems([]);
        setEdited(false);
        toast.success("JSON applied — form, visual and backtest now use this version");
      } else {
        setProblems((r.errors ?? []) as { path?: string; message?: string }[]);
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const shown = problems.length ? problems : edited ? [] : errors;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-2 text-xs">
        <span className="text-muted-foreground">
          The strategy as stored and executed (DSL v{dsl.dsl_version ?? "1.0"}). Edit it directly; the schema validates as you type.
        </span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" disabled={!edited} onClick={() => { setText(pretty); setEdited(false); setProblems([]); }}>
            <RotateCcw /> Revert
          </Button>
          <Button size="sm" disabled={!edited} loading={busy} onClick={apply}>
            <Check /> Apply JSON
          </Button>
        </div>
      </div>
      {shown.length > 0 && (
        <div className="rounded-lg border border-loss/30 bg-loss/5 p-2 text-xs text-loss" role="alert">
          {shown.map((e, i) => (
            <div key={i}>
              {e.path && <b>{e.path}</b>}
              {e.path ? ": " : ""}
              {e.message}
            </div>
          ))}
        </div>
      )}
      <div className="overflow-hidden rounded-lg border">
        <CodeEditor
          language="json"
          height={600}
          value={text}
          beforeMount={beforeMount}
          onChange={(v) => {
            setText(v);
            setEdited(v !== pretty);
          }}
        />
      </div>
    </div>
  );
}
