"use client";
import { create } from "zustand";
import { blankDsl, type DSL } from "./dsl";

/** sessionStorage key used by "Send to Builder" (AI copilot) to hand over a DSL draft. */
export const DRAFT_KEY = "algodesk-builder-draft";

export type BuilderMode = "form" | "visual" | "code" | "json";

interface BuilderState {
  strategyId: number | null;
  version: number;
  dsl: DSL;
  code: string | null;
  graph: Record<string, unknown> | null;
  mode: BuilderMode;
  dirty: boolean;
  errors: { path: string; message: string }[];
  load: (p: { id: number | null; version?: number; dsl: DSL; code?: string | null; graph?: Record<string, unknown> | null }) => void;
  update: (fn: (d: DSL) => DSL | void) => void;
  setDsl: (d: DSL) => void;
  setCode: (c: string) => void;
  setGraph: (g: Record<string, unknown> | null) => void;
  setMode: (m: BuilderMode) => void;
  setErrors: (e: { path: string; message: string }[]) => void;
  markSaved: (id: number, version: number) => void;
}

export const useBuilder = create<BuilderState>((set) => ({
  strategyId: null,
  version: 0,
  dsl: blankDsl(),
  code: null,
  graph: null,
  mode: "form",
  dirty: false,
  errors: [],
  load: ({ id, version = 0, dsl, code = null, graph = null }) => set({ strategyId: id, version, dsl, code, graph, dirty: false, errors: [] }),
  update: (fn) =>
    set((s) => {
      const draft = structuredClone(s.dsl);
      const res = fn(draft);
      return { dsl: res ?? draft, dirty: true };
    }),
  setDsl: (dsl) => set({ dsl, dirty: true }),
  setCode: (code) => set({ code, dirty: true }),
  setGraph: (graph) => set({ graph }),
  setMode: (mode) => set({ mode }),
  setErrors: (errors) => set({ errors }),
  markSaved: (id, version) => set({ strategyId: id, version, dirty: false }),
}));
