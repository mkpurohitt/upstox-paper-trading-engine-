"use client";
import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useIndicatorCatalog } from "@/hooks/use-catalog";
import { useBuilder } from "@/lib/builder-store";
import { DAYS, OP_LABEL, OPS, PATTERNS, PRICE_FIELDS, slugId } from "@/lib/dsl";
import { canonical, dslToGraph, GraphError, graphToDsl, type Graph } from "@/lib/graph";
import { cn } from "@/lib/utils";

type Patch = (id: string, data: Record<string, unknown>) => void;
const Ctx = React.createContext<Patch>(() => undefined);

const box = "rounded-lg border bg-card text-card-foreground shadow-md text-xs min-w-[150px]";
const hdr = "flex items-center justify-between gap-2 rounded-t-lg border-b px-2 py-1 font-semibold";
const inp = "nodrag h-6 w-full rounded border border-input bg-background px-1 text-xs";

function IndicatorNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  const outputs = (data.outputs as string[]) ?? ["value"];
  const params = (data.params as Record<string, number>) ?? {};
  return (
    <div className={cn(box, "border-info/40")}>
      <div className={cn(hdr, "bg-info/10 text-info")}>
        <span>{String(data.kind)}</span>
        <input className={cn(inp, "w-24")} value={String(data.id)} aria-label="Indicator id" onChange={(e) => patch(id, { id: slugId(e.target.value) })} />
      </div>
      <div className="flex flex-col gap-1 p-2">
        {Object.entries(params).map(([k, v]) => (
          <label key={k} className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">{k}</span>
            <input className={cn(inp, "w-16")} type="number" step="any" value={v} onChange={(e) => patch(id, { params: { ...params, [k]: Number(e.target.value) } })} />
          </label>
        ))}
        {!Object.keys(params).length && <span className="text-muted-foreground">no params</span>}
      </div>
      {outputs.map((o, i) => (
        <Handle key={o} id={outputs.length > 1 ? o : undefined} type="source" position={Position.Right} style={{ top: 30 + i * 16 }} className="!h-2.5 !w-2.5 !bg-info">
          {outputs.length > 1 && <span className="pointer-events-none absolute left-3 -top-1.5 text-[9px] text-muted-foreground">{o}</span>}
        </Handle>
      ))}
    </div>
  );
}

function PriceNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  return (
    <div className={cn(box, "min-w-[110px]")}>
      <div className={cn(hdr, "bg-muted")}>Price</div>
      <div className="p-2">
        <select className={inp} value={String(data.field)} onChange={(e) => patch(id, { field: e.target.value })} aria-label="Price field">
          {PRICE_FIELDS.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-foreground" />
    </div>
  );
}

function ConstNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  return (
    <div className={cn(box, "min-w-[100px]")}>
      <div className={cn(hdr, "bg-muted")}>Value</div>
      <div className="p-2">
        <input className={inp} type="number" step="any" value={Number(data.value)} onChange={(e) => patch(id, { value: Number(e.target.value) })} aria-label="Constant value" />
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-foreground" />
    </div>
  );
}

function CompareNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  return (
    <div className={cn(box, "border-primary/40")}>
      <Handle id="left" type="target" position={Position.Left} style={{ top: 34 }} className="!h-2.5 !w-2.5 !bg-primary" />
      <Handle id="right" type="target" position={Position.Left} style={{ top: 70 }} className="!h-2.5 !w-2.5 !bg-primary" />
      <div className={cn(hdr, "bg-primary/10 text-primary")}>Compare</div>
      <div className="flex flex-col gap-1 p-2">
        <label className="flex items-center gap-1">
          <span className="w-8 text-muted-foreground">A[-n]</span>
          <input className={cn(inp, "w-12")} type="number" min={0} value={Number(data.leftOffset ?? 0)} onChange={(e) => patch(id, { leftOffset: Number(e.target.value) })} aria-label="Left offset" />
        </label>
        <select className={inp} value={String(data.op)} onChange={(e) => patch(id, { op: e.target.value })} aria-label="Operator">
          {OPS.map((o) => (
            <option key={o} value={o}>
              {OP_LABEL[o]}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1">
          <span className="w-8 text-muted-foreground">B[-n]</span>
          <input className={cn(inp, "w-12")} type="number" min={0} value={Number(data.rightOffset ?? 0)} onChange={(e) => patch(id, { rightOffset: Number(e.target.value) })} aria-label="Right offset" />
        </label>
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-primary" />
    </div>
  );
}

function LogicNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  const k = data.kind as "all" | "any";
  return (
    <div className={cn(box, "min-w-[90px] border-warning/50")}>
      <Handle id="in" type="target" position={Position.Left} className="!h-3 !w-3 !bg-warning" />
      <button type="button" className="nodrag w-full rounded-lg px-3 py-2 text-sm font-bold text-warning" onClick={() => patch(id, { kind: k === "all" ? "any" : "all" })} title="Click to toggle">
        {k === "all" ? "AND" : "OR"}
      </button>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-warning" />
    </div>
  );
}

function TimeNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  return (
    <div className={box}>
      <div className={cn(hdr, "bg-muted")}>Time window (IST)</div>
      <div className="flex gap-1 p-2">
        <input className={inp} type="time" value={String(data.after ?? "")} onChange={(e) => patch(id, { after: e.target.value || null })} aria-label="After" />
        <input className={inp} type="time" value={String(data.before ?? "")} onChange={(e) => patch(id, { before: e.target.value || null })} aria-label="Before" />
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-foreground" />
    </div>
  );
}

function DayNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  const days = (data.days as string[]) ?? [];
  return (
    <div className={box}>
      <div className={cn(hdr, "bg-muted")}>Days</div>
      <div className="flex gap-0.5 p-2">
        {DAYS.map((d) => (
          <button key={d} type="button" className={cn("nodrag rounded px-1 text-[10px]", days.includes(d) ? "bg-primary/20 text-primary" : "bg-muted")} onClick={() => patch(id, { days: days.includes(d) ? days.filter((x) => x !== d) : [...days, d] })}>
            {d}
          </button>
        ))}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-foreground" />
    </div>
  );
}

function PatternNode({ id, data }: NodeProps) {
  const patch = React.useContext(Ctx);
  return (
    <div className={box}>
      <div className={cn(hdr, "bg-muted")}>Pattern</div>
      <div className="p-2">
        <select className={inp} value={String(data.name)} onChange={(e) => patch(id, { name: e.target.value })} aria-label="Pattern">
          {PATTERNS.map((p) => (
            <option key={p} value={p}>
              {p.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-foreground" />
    </div>
  );
}

function ActionNode({ data }: NodeProps) {
  const a = String(data.action);
  const long = a.endsWith("long");
  const entry = a.startsWith("entry");
  return (
    <div className={cn(box, "min-w-[130px]", long ? "border-profit/50" : "border-loss/50")}>
      <Handle id="in" type="target" position={Position.Left} className={cn("!h-3 !w-3", long ? "!bg-profit" : "!bg-loss")} />
      <div className={cn("rounded-lg px-3 py-2 text-sm font-semibold", long ? "text-profit" : "text-loss")}>
        {entry ? "Enter" : "Exit"} {long ? "LONG" : "SHORT"}
      </div>
    </div>
  );
}

const nodeTypes = { indicator: IndicatorNode, price: PriceNode, const: ConstNode, compare: CompareNode, logic: LogicNode, time: TimeNode, day: DayNode, pattern: PatternNode, action: ActionNode };

export function VisualBuilder() {
  const dsl = useBuilder((s) => s.dsl);
  const setDsl = useBuilder((s) => s.setDsl);
  const saved = useBuilder((s) => s.graph);
  const setGraph = useBuilder((s) => s.setGraph);
  const { data: catalog } = useIndicatorCatalog();
  const { resolvedTheme } = useTheme();
  const initial = React.useMemo(() => {
    const g = dslToGraph(dsl, catalog);
    const pos = new Map(((saved as Graph | null)?.nodes ?? []).map((n) => [n.id, n.position]));
    return { nodes: g.nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position })) as Node[], edges: g.edges as Edge[] };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges);
  const [error, setError] = React.useState<string | null>(null);
  const [addKind, setAddKind] = React.useState<string | undefined>(undefined);
  const counter = React.useRef(1000);

  React.useEffect(() => {
    setNodes(initial.nodes);
    setEdges(initial.edges);
  }, [initial, setNodes, setEdges]);

  // compile on structural / data changes
  React.useEffect(() => {
    const g: Graph = { nodes: nodes.map((n) => ({ id: n.id, type: n.type ?? "", position: n.position, data: n.data })), edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle })) };
    try {
      const next = graphToDsl(g, useBuilder.getState().dsl);
      setError(null);
      if (canonical(next) !== canonical(useBuilder.getState().dsl)) setDsl(next);
      setGraph(g as unknown as Record<string, unknown>);
    } catch (e) {
      setError(e instanceof GraphError ? e.message : String(e));
    }
  }, [nodes, edges, setDsl, setGraph]);

  const patch: Patch = React.useCallback((id, data) => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...data } } : n))), [setNodes]);

  const isValid = React.useCallback(
    (c: Connection | Edge) => {
      const src = nodes.find((n) => n.id === c.source);
      const tgt = nodes.find((n) => n.id === c.target);
      if (!src || !tgt) return false;
      if (tgt.type === "compare") return ["indicator", "price", "const"].includes(src.type ?? "");
      if (tgt.type === "logic" || tgt.type === "action") return ["compare", "logic", "time", "day", "pattern"].includes(src.type ?? "");
      return false;
    },
    [nodes],
  );

  const onConnect = React.useCallback(
    (c: Connection) =>
      setEdges((es) => {
        // comparison inputs and action inputs take a single edge
        const filtered = es.filter((e) => !(e.target === c.target && e.targetHandle === c.targetHandle && (c.targetHandle === "left" || c.targetHandle === "right" || nodes.find((n) => n.id === c.target)?.type === "action")));
        return addEdge({ ...c, animated: true }, filtered);
      }),
    [setEdges, nodes],
  );

  const add = (type: string, data: Record<string, unknown>) => {
    const id = `${type}_${counter.current++}`;
    setNodes((ns) => [...ns, { id, type, position: { x: 120 + Math.random() * 200, y: 60 + Math.random() * 300 }, data }]);
  };

  const addIndicator = (kind: string) => {
    const spec = catalog?.find((c) => c.kind === kind);
    const params: Record<string, number> = {};
    spec?.params.forEach((p) => (params[p.name] = p.default));
    let idBase = slugId(kind);
    const ids = new Set(nodes.filter((n) => n.type === "indicator").map((n) => n.data.id));
    let k = 2;
    while (ids.has(idBase)) idBase = `${slugId(kind)}_${k++}`;
    add("indicator", { id: idBase, kind, params, source: spec?.default_source ?? "close", outputs: spec?.outputs ?? ["value"] });
    setAddKind(undefined);
  };

  if (dsl.kind !== "equity") {
    return (
      <div className="rounded-lg border p-6 text-sm text-muted-foreground">
        The visual canvas edits signal logic for <b>equity / futures</b> strategies. Options legs and pair settings are edited in <b>Form</b> mode; both modes produce the same DSL.
      </div>
    );
  }

  return (
    <Ctx.Provider value={patch}>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5 rounded-lg border bg-card p-2">
          <Select ariaLabel="Add indicator node" className="h-8 w-44 text-xs" value={addKind} placeholder="+ Indicator" onValueChange={addIndicator} options={(catalog ?? []).filter((c) => c.kind !== "CUSTOM").map((c) => ({ value: c.kind, label: c.kind }))} />
          <Button size="xs" variant="outline" onClick={() => add("price", { field: "close" })}>+ Price</Button>
          <Button size="xs" variant="outline" onClick={() => add("const", { value: 50 })}>+ Value</Button>
          <Button size="xs" variant="outline" onClick={() => add("compare", { op: "crosses_above", leftOffset: 0, rightOffset: 0 })}>+ Compare</Button>
          <Button size="xs" variant="outline" onClick={() => add("logic", { kind: "all" })}>+ AND</Button>
          <Button size="xs" variant="outline" onClick={() => add("logic", { kind: "any" })}>+ OR</Button>
          <Button size="xs" variant="outline" onClick={() => add("time", { after: "09:30", before: "15:00" })}>+ Time</Button>
          <Button size="xs" variant="outline" onClick={() => add("pattern", { name: "bullish_engulfing", lookback: 20 })}>+ Pattern</Button>
          <Button size="xs" variant="outline" onClick={() => add("day", { days: [...DAYS] })}>+ Days</Button>
          <span className="ml-auto flex items-center gap-1 text-2xs">
            {error ? (
              <Badge variant="warning" className="gap-1">
                <AlertTriangle className="h-3 w-3" /> {error}
              </Badge>
            ) : (
              <Badge variant="profit" className="gap-1">
                <CheckCircle2 className="h-3 w-3" /> compiles to DSL
              </Badge>
            )}
          </span>
        </div>
        <div className="h-[620px] overflow-hidden rounded-lg border bg-surface">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValid}
            nodeTypes={nodeTypes}
            colorMode={resolvedTheme === "light" ? "light" : "dark"}
            fitView
            deleteKeyCode={["Backspace", "Delete"]}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <p className="text-2xs text-muted-foreground">
          Drag from an indicator / price / value output into a Compare node&apos;s A (top) or B (bottom) input, chain comparisons through AND/OR, and connect them to an action. Select a node or edge and press Delete to remove it. Stops and sizing are edited in Form mode.
        </p>
      </div>
    </Ctx.Provider>
  );
}

export { PRICE_FIELDS };
