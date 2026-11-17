"use client";
import Editor from "@monaco-editor/react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Play, ShieldCheck, XCircle } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { api, unwrap } from "@/lib/api";
import { useBuilder } from "@/lib/builder-store";
import type { DSL } from "@/lib/dsl";

export function CodeBuilder() {
  const code = useBuilder((s) => s.code);
  const setCode = useBuilder((s) => s.setCode);
  const setDsl = useBuilder((s) => s.setDsl);
  const { resolvedTheme } = useTheme();
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
          <Editor
            height="560px"
            language="python"
            theme={resolvedTheme === "light" ? "light" : "vs-dark"}
            value={code}
            onChange={(v) => setCode(v ?? "")}
            options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, tabSize: 4, wordWrap: "on", fontFamily: "var(--font-geist-mono)" }}
          />
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
  const errors = useBuilder((s) => s.errors);
  return (
    <div className="flex flex-col gap-2">
      {errors.length > 0 && (
        <div className="rounded-lg border border-loss/30 bg-loss/5 p-2 text-xs text-loss">
          {errors.map((e, i) => (
            <div key={i}>
              <b>{e.path}</b>: {e.message}
            </div>
          ))}
        </div>
      )}
      <pre className="max-h-[640px] overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed">{JSON.stringify(dsl, null, 2)}</pre>
    </div>
  );
}
