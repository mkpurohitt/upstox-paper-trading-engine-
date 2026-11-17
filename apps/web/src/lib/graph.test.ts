import { describe, expect, it } from "vitest";
import { blankDsl, type DSL } from "./dsl";
import { canonical, dslToGraph, graphToDsl } from "./graph";

const CATALOG = [
  { kind: "EMA", description: "", outputs: ["value"], overlay: true, default_source: "close", params: [{ name: "period", default: 20, min: 1, max: 500 }] },
  { kind: "MACD", description: "", outputs: ["macd", "signal", "hist"], overlay: false, default_source: "close", params: [] },
];

describe("dsl <-> graph", () => {
  it("round-trips the default equity strategy", () => {
    const dsl = blankDsl("equity");
    const g = dslToGraph(dsl, CATALOG);
    expect(g.nodes.filter((n) => n.type === "indicator")).toHaveLength(2);
    expect(g.nodes.filter((n) => n.type === "action")).toHaveLength(4);
    const back = graphToDsl(g, dsl);
    expect(canonical(back.entry)).toEqual(canonical(dsl.entry));
    expect(canonical(back.indicators)).toEqual(canonical(dsl.indicators));
  });

  it("handles multi-output indicators and nested groups", () => {
    const dsl: DSL = {
      ...blankDsl("equity"),
      indicators: [{ id: "m", kind: "MACD", params: {}, source: "close" }],
      exit: {},
      entry: {
        long: {
          kind: "all",
          conditions: [
            { kind: "compare", left: { type: "indicator", ref: "m.macd", offset: 0 }, op: "crosses_above", right: { type: "indicator", ref: "m.signal", offset: 1 } },
            { kind: "any", conditions: [{ kind: "time", after: "09:30", before: "11:00" }, { kind: "pattern", name: "hammer", lookback: 20 }] },
          ],
        },
      },
    };
    const back = graphToDsl(dslToGraph(dsl, CATALOG), dsl);
    expect(canonical(back.entry?.long)).toEqual(canonical(dsl.entry?.long));
  });

  it("reports missing comparison inputs", () => {
    const dsl = blankDsl("equity");
    const g = dslToGraph(dsl, CATALOG);
    const cmp = g.nodes.find((n) => n.type === "compare")!;
    g.edges = g.edges.filter((e) => !(e.target === cmp.id && e.targetHandle === "right"));
    expect(() => graphToDsl(g, dsl)).toThrow(/missing its right input/);
  });
});
