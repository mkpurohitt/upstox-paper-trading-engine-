/**
 * DSL <-> node graph conversion for the visual (React Flow) builder.
 *
 * Node types: indicator | price | const | compare | logic | time | day | pattern | action
 * Edges carry `targetHandle` ("left" | "right" | "in") and, for multi-output
 * indicators, `sourceHandle` = output name.
 */
import type { Compare, Condition, DSL, Group, IndicatorCatalog, Operand } from "./dsl";

export interface GNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}
export interface GEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}
export interface Graph {
  nodes: GNode[];
  edges: GEdge[];
}

export const ACTIONS = ["entry_long", "entry_short", "exit_long", "exit_short"] as const;
type Action = (typeof ACTIONS)[number];

const COL = { input: 0, cond: 320, logic: 620, action: 900 };

export function dslToGraph(dsl: DSL, catalog?: IndicatorCatalog[]): Graph {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  let seq = 0;
  const nid = (p: string) => `${p}_${++seq}`;
  const rows = { input: 0, cond: 0, logic: 0 };
  const GAP = { input: 120, cond: 165, logic: 120 } as const;
  const place = (col: keyof typeof rows) => ({ x: COL[col], y: 40 + rows[col]++ * GAP[col] });

  const indNode: Record<string, string> = {};
  for (const ind of dsl.indicators ?? []) {
    const id = `ind_${ind.id}`;
    indNode[ind.id] = id;
    const spec = catalog?.find((c) => c.kind === ind.kind);
    nodes.push({ id, type: "indicator", position: place("input"), data: { id: ind.id, kind: ind.kind, params: ind.params ?? {}, source: ind.source ?? "close", outputs: spec?.outputs ?? ["value"], code: ind.code ?? null } });
  }
  const priceNodes: Record<string, string> = {};
  const operandSource = (o: Operand): { node: string; handle: string | null; offset: number } => {
    if (o.type === "indicator") {
      const [base, out] = o.ref.split(".");
      return { node: indNode[base ?? ""] ?? "", handle: out ?? null, offset: o.offset ?? 0 };
    }
    if (o.type === "price") {
      const f = o.field ?? "close";
      if (!priceNodes[f]) {
        priceNodes[f] = nid("price");
        nodes.push({ id: priceNodes[f]!, type: "price", position: place("input"), data: { field: f } });
      }
      return { node: priceNodes[f]!, handle: null, offset: o.offset ?? 0 };
    }
    const id = nid("const");
    nodes.push({ id, type: "const", position: place("input"), data: { value: o.value } });
    return { node: id, handle: null, offset: 0 };
  };

  const build = (c: Condition): string => {
    if (c.kind === "all" || c.kind === "any") {
      const id = nid("logic");
      nodes.push({ id, type: "logic", position: place("logic"), data: { kind: c.kind } });
      for (const child of ((c as Group).conditions ?? []) as Condition[]) {
        edges.push({ id: nid("e"), source: build(child), target: id, targetHandle: "in" });
      }
      return id;
    }
    if (c.kind === "compare") {
      const cc = c as Compare;
      const id = nid("cmp");
      const l = operandSource(cc.left as Operand);
      const r = operandSource(cc.right as Operand);
      nodes.push({ id, type: "compare", position: place("cond"), data: { op: cc.op, leftOffset: l.offset, rightOffset: r.offset } });
      edges.push({ id: nid("e"), source: l.node, sourceHandle: l.handle, target: id, targetHandle: "left" });
      edges.push({ id: nid("e"), source: r.node, sourceHandle: r.handle, target: id, targetHandle: "right" });
      return id;
    }
    const id = nid(c.kind);
    nodes.push({ id, type: c.kind === "day_of_week" ? "day" : c.kind, position: place("cond"), data: { ...c } });
    return id;
  };

  ACTIONS.forEach((a, i) => {
    const [which, side] = a.split("_") as ["entry" | "exit", "long" | "short"];
    const g = (dsl[which] as Record<string, Group | null | undefined> | undefined)?.[side];
    const id = `act_${a}`;
    nodes.push({ id, type: "action", position: { x: COL.action, y: 40 + i * 150 }, data: { action: a, enabled: !!g } });
    if (g) edges.push({ id: nid("e"), source: build(g), target: id, targetHandle: "in" });
  });
  return { nodes, edges };
}

export class GraphError extends Error {}

/** Compile the graph back into the DSL fields it controls (indicators, entry, exit). */
export function graphToDsl(graph: Graph, base: DSL): DSL {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const incoming = (target: string, handle?: string) =>
    graph.edges.filter((e) => e.target === target && (handle === undefined || (e.targetHandle ?? "in") === handle));

  const operand = (target: string, handle: "left" | "right", offset: number): Operand => {
    const e = incoming(target, handle)[0];
    if (!e) throw new GraphError(`A comparison is missing its ${handle} input`);
    const src = byId.get(e.source);
    if (!src) throw new GraphError("A comparison input references an indicator that no longer exists");
    if (src.type === "indicator") {
      const outs = (src.data.outputs as string[]) ?? ["value"];
      const ref = outs.length > 1 ? `${src.data.id}.${e.sourceHandle ?? outs[0]}` : String(src.data.id);
      return { type: "indicator", ref, offset };
    }
    if (src.type === "price") return { type: "price", field: src.data.field as "close", offset };
    if (src.type === "const") return { type: "const", value: Number(src.data.value) };
    throw new GraphError(`'${src.type}' cannot feed a comparison input`);
  };

  const seen = new Set<string>();
  const cond = (id: string): Condition => {
    if (seen.has(id)) throw new GraphError("Cycle detected in the graph");
    seen.add(id);
    const n = byId.get(id);
    if (!n) throw new GraphError("Unknown node");
    try {
      if (n.type === "logic") {
        const kids = incoming(id, "in").map((e) => cond(e.source));
        return { kind: (n.data.kind as "all" | "any") ?? "all", conditions: kids as Group["conditions"] };
      }
      if (n.type === "compare") {
        return { kind: "compare", op: n.data.op as Compare["op"], left: operand(id, "left", Number(n.data.leftOffset ?? 0)), right: operand(id, "right", Number(n.data.rightOffset ?? 0)) };
      }
      if (n.type === "time") return { kind: "time", after: (n.data.after as string) ?? null, before: (n.data.before as string) ?? null };
      if (n.type === "day") return { kind: "day_of_week", days: n.data.days as ("MON" | "TUE" | "WED" | "THU" | "FRI")[] };
      if (n.type === "pattern") return { kind: "pattern", name: n.data.name as "doji", lookback: Number(n.data.lookback ?? 20) };
      throw new GraphError(`'${n.type}' node cannot be used as a condition`);
    } finally {
      seen.delete(id);
    }
  };

  const out: DSL = structuredClone(base);
  out.indicators = graph.nodes
    .filter((n) => n.type === "indicator")
    .map((n) => ({
      id: String(n.data.id),
      kind: String(n.data.kind),
      params: (n.data.params as Record<string, number>) ?? {},
      source: (n.data.source as "close") ?? "close",
      ...(n.data.code ? { code: n.data.code as string } : {}),
    }));
  out.entry = { long: null, short: null };
  out.exit = { ...(base.exit ?? {}), long: null, short: null };
  for (const a of ACTIONS) {
    const node = graph.nodes.find((n) => n.type === "action" && n.data.action === a);
    if (!node) continue;
    const e = incoming(node.id, "in")[0];
    if (!e) continue;
    let c = cond(e.source);
    if (c.kind !== "all" && c.kind !== "any") c = { kind: "all", conditions: [c] as Group["conditions"] };
    const [which, side] = (a as Action).split("_") as ["entry" | "exit", "long" | "short"];
    (out[which] as Record<string, unknown>)[side] = c;
  }
  return out;
}

/** Canonical JSON (drops null / undefined) used to detect real DSL changes. */
export function canonical(v: unknown): string {
  const strip = (x: unknown): unknown => {
    if (Array.isArray(x)) return x.map(strip);
    if (x && typeof x === "object") {
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(x as object).sort()) {
        const val = (x as Record<string, unknown>)[k];
        if (val !== null && val !== undefined) out[k] = strip(val);
      }
      return out;
    }
    return x;
  };
  return JSON.stringify(strip(v));
}
