"use client";
import type { Schemas } from "@algo/api-client";
import { create } from "zustand";
import { getCookie } from "./utils";

export type User = Schemas["UserOut"];
type TokenOut = Schemas["TokenOut"];

interface AuthState {
  token: string | null;
  user: User | null;
  status: "idle" | "loading" | "authenticated" | "anonymous";
  setSession: (t: TokenOut) => void;
  setUser: (u: User) => void;
  refresh: () => Promise<string | null>;
  bootstrap: () => Promise<void>;
  logout: () => Promise<void>;
}

let inflight: Promise<string | null> | null = null;

export const useAuth = create<AuthState>((set, get) => ({
  token: null,
  user: null,
  status: "idle",
  setSession: (t) => set({ token: t.access_token, user: t.user, status: "authenticated" }),
  setUser: (u) => set({ user: u }),
  refresh: () => {
    if (inflight) return inflight;
    inflight = (async () => {
      try {
        const res = await fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRF-Token": getCookie("algo_csrf") ?? "" },
        });
        if (!res.ok) {
          set({ token: null, user: null, status: "anonymous" });
          return null;
        }
        const t = (await res.json()) as TokenOut;
        get().setSession(t);
        return t.access_token;
      } catch {
        set({ status: "anonymous" });
        return null;
      } finally {
        setTimeout(() => (inflight = null), 0);
      }
    })();
    return inflight;
  },
  bootstrap: async () => {
    if (get().status === "authenticated" || get().status === "loading") return;
    set({ status: "loading" });
    await get().refresh();
  },
  logout: async () => {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": getCookie("algo_csrf") ?? "" },
    }).catch(() => undefined);
    set({ token: null, user: null, status: "anonymous" });
  },
}));
