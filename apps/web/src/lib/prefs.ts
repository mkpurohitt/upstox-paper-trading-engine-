"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface Prefs {
  colourBlind: boolean;
  sidebarCollapsed: boolean;
  density: "comfortable" | "compact";
  copilotContext: string | null;
  setColourBlind: (v: boolean) => void;
  toggleSidebar: () => void;
  setDensity: (d: Prefs["density"]) => void;
  setCopilotContext: (c: string | null) => void;
}

export const usePrefs = create<Prefs>()(
  persist(
    (set) => ({
      colourBlind: false,
      sidebarCollapsed: false,
      density: "comfortable",
      copilotContext: null,
      setColourBlind: (v) => set({ colourBlind: v }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setDensity: (d) => set({ density: d }),
      setCopilotContext: (c) => set({ copilotContext: c }),
    }),
    { name: "algodesk-prefs", partialize: (s) => ({ colourBlind: s.colourBlind, sidebarCollapsed: s.sidebarCollapsed, density: s.density }) },
  ),
);
