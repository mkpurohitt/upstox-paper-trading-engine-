"use client";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Braces, CheckCircle2, Code2, FileSliders, FlaskConical, GitBranch, Rocket, Save, Workflow, Wand2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import dynamic from "next/dynamic";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { api, ApiError, unwrap } from "@/lib/api";
import { useBuilder, type BuilderMode } from "@/lib/builder-store";
import { describe } from "@/lib/dsl";
import { cn } from "@/lib/utils";
import { FormBuilder } from "./form-builder";

// Heavy editors / charts are split into their own chunks and loaded on demand.
const Loading = () => <div className="h-96 animate-pulse rounded-lg bg-muted" />;
const VisualBuilder = dynamic(() => import("./visual-builder").then((m) => m.VisualBuilder), { ssr: false, loading: Loading });
const CodeBuilder = dynamic(() => import("./code-builder").then((m) => m.CodeBuilder), { ssr: false, loading: Loading });
const JsonView = dynamic(() => import("./code-builder").then((m) => m.JsonView), { ssr: false, loading: Loading });
const BacktestPanel = dynamic(() => import("@/components/backtest/run-panels").then((m) => m.BacktestPanel), { ssr: false, loading: Loading });
const OptimisePanel = dynamic(() => import("@/components/backtest/run-panels").then((m) => m.OptimisePanel), { ssr: false, loading: Loading });
const WalkForwardPanel = dynamic(() => import("@/components/backtest/run-panels").then((m) => m.WalkForwardPanel), { ssr: false, loading: Loading });

const MODES: { id: BuilderMode; label: string; icon: typeof FileSliders }[] = [
  { id: "form", label: "Form", icon: FileSliders },
  { id: "visual", label: "Visual", icon: Workflow },
  { id: "code", label: "Code", icon: Code2 },
  { id: "json", label: "DSL", icon: Braces },
];

function useLiveValidation() {
  const dsl = useBuilder((s) => s.dsl);
  const setErrors = useBuilder((s) => s.setErrors);
  React.useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const r = await unwrap(api.POST("/api/strategies/validate", { body: dsl as unknown as Record<string, never> }));
        setErrors((r.errors ?? []) as { path: string; message: string }[]);
      } catch {
        /* network errors are surfaced on save */
      }
    }, 350);
    return () => clearTimeout(t);
  }, [dsl, setErrors]);
}

export function Builder({ deployPanel }: { deployPanel?: React.ReactNode }) {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { dsl, mode, setMode, dirty, errors, strategyId, version, update } = useBuilder();
  const [tab, setTab] = React.useState(params.get("tab") ?? "design");
  const [saving, setSaving] = React.useState(false);
  useLiveValidation();
  React.useEffect(() => {
    const m = params.get("mode");
    if (m === "form" || m === "visual" || m === "code" || m === "json") setMode(m);
  }, [params, setMode]);

  const save = React.useCallback(async (): Promise<number | null> => {
    const s = useBuilder.getState();
    if (s.errors.length) {
      toast.error(`Fix ${s.errors.length} validation error(s) first`);
      return null;
    }
    setSaving(true);
    try {
      const body = { dsl: s.dsl, source: s.mode === "code" ? "code" : s.mode === "visual" ? "visual" : "form", code: s.code, graph: s.graph } as const;
      const out = s.strategyId
        ? await unwrap(api.PUT("/api/strategies/{strategy_id}", { params: { path: { strategy_id: s.strategyId } }, body }))
        : await unwrap(api.POST("/api/strategies", { body }));
      s.markSaved(out.id, out.version);
      void qc.invalidateQueries({ queryKey: ["strategies"] });
      if (!s.strategyId) router.replace(`/build/${out.id}?tab=${tab}`);
      toast.success(`Saved v${out.version}`);
      return out.id;
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Save failed");
      return null;
    } finally {
      setSaving(false);
    }
  }, [qc, router, tab]);

  const ensureSaved = React.useCallback(async () => {
    const s = useBuilder.getState();
    if (s.strategyId && !s.dirty) return s.strategyId;
    return save();
  }, [save]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);

  return (
    <div className="mx-auto flex max-w-[1440px] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="icon-sm" asChild aria-label="Back to strategies">
          <Link href="/build">
            <ArrowLeft />
          </Link>
        </Button>
        <Input value={dsl.name} onChange={(e) => update((d) => void (d.name = e.target.value))} className="h-9 max-w-md border-transparent bg-transparent text-lg font-semibold hover:border-input focus:border-input" aria-label="Strategy name" />
        <Badge variant="secondary" className="capitalize">
          {dsl.kind}
        </Badge>
        {strategyId ? (
          <Badge variant="outline" className="gap-1">
            <GitBranch className="h-3 w-3" /> v{version}
            {dirty && " • unsaved"}
          </Badge>
        ) : (
          <Badge variant="warning">draft</Badge>
        )}
        <Tooltip content={errors.length ? errors.map((e) => `${e.path}: ${e.message}`).join("\n") : "Valid DSL v1.0"}>
          <span className={cn("flex items-center gap-1 text-xs", errors.length ? "text-loss" : "text-profit")}>
            {errors.length ? <AlertCircle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            {errors.length ? `${errors.length} issue${errors.length > 1 ? "s" : ""}` : "valid"}
          </span>
        </Tooltip>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" onClick={() => void save()} loading={saving} disabled={!dirty && !!strategyId}>
            <Save /> Save
          </Button>
          <Button onClick={() => setTab("deploy")} disabled={!strategyId}>
            <Rocket /> Deploy
          </Button>
        </div>
      </div>
      {errors.length > 0 && tab === "design" && (
        <div className="rounded-lg border border-loss/30 bg-loss/5 px-3 py-2 text-xs text-loss">
          {errors.slice(0, 3).map((e, i) => (
            <div key={i}>
              <b className="font-mono">{e.path || "strategy"}</b> — {e.message}
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-profit">Entry long</span>: {describe(dsl.entry?.long)} · <span className="font-medium text-loss">Entry short</span>: {describe(dsl.entry?.short)}
      </p>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="design">
            <FileSliders /> Design
          </TabsTrigger>
          <TabsTrigger value="backtest">
            <FlaskConical /> Backtest
          </TabsTrigger>
          <TabsTrigger value="optimise" disabled={dsl.kind === "options"}>
            <Wand2 /> Optimise
          </TabsTrigger>
          <TabsTrigger value="walkforward" disabled={dsl.kind === "options"}>
            <GitBranch /> Walk-forward
          </TabsTrigger>
          <TabsTrigger value="deploy">
            <Rocket /> Deploy
          </TabsTrigger>
        </TabsList>
        <TabsContent value="design" className="flex flex-col gap-3">
          <div className="inline-flex w-fit rounded-lg border bg-card p-1" role="tablist" aria-label="Builder mode">
            {MODES.map((m) => (
              <button key={m.id} role="tab" aria-selected={mode === m.id} onClick={() => setMode(m.id)} className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors", mode === m.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                <m.icon className="h-3.5 w-3.5" /> {m.label}
              </button>
            ))}
          </div>
          {mode === "form" && <FormBuilder />}
          {mode === "visual" && <VisualBuilder />}
          {mode === "code" && <CodeBuilder />}
          {mode === "json" && <JsonView />}
        </TabsContent>
        <TabsContent value="backtest">
          <BacktestPanel ensureSaved={ensureSaved} />
        </TabsContent>
        <TabsContent value="optimise">
          <OptimisePanel ensureSaved={ensureSaved} />
        </TabsContent>
        <TabsContent value="walkforward">
          <WalkForwardPanel ensureSaved={ensureSaved} />
        </TabsContent>
        <TabsContent value="deploy">{deployPanel ?? <p className="text-sm text-muted-foreground">Save the strategy to deploy it.</p>}</TabsContent>
      </Tabs>
    </div>
  );
}
