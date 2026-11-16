"use client";
/**
 * Realtime client: one multiplexed WebSocket per tab with auto-reconnect
 * (exponential backoff + jitter), re-authentication and automatic
 * re-subscription, plus ref-counted subscriptions so many components can share
 * the same tick stream.
 */
import { create } from "zustand";

export type WsStatus = "idle" | "connecting" | "open" | "closed";
export type Spec =
  | { channel: "ticks"; symbols: string[] }
  | { channel: "orders" | "deployments" | "notifications" }
  | { channel: "backtest"; id: number }
  | { channel: "scanner"; name: string };

export interface Frame {
  type: string;
  channel?: string;
  data?: unknown;
  [k: string]: unknown;
}
type Handler = (frame: Frame) => void;

export const useWsStatus = create<{ status: WsStatus; set: (s: WsStatus) => void }>((set) => ({
  status: "idle",
  set: (status) => set({ status }),
}));

function keysFor(spec: Spec): string[] {
  switch (spec.channel) {
    case "ticks":
      return spec.symbols.map((s) => `ticks:${s}`);
    case "orders":
      return ["orders:*"];
    case "deployments":
      return ["deploy:*"];
    case "notifications":
      return ["notify:*"];
    case "backtest":
      return [`backtest:${spec.id}`];
    case "scanner":
      return [`scanner:${spec.name}`];
  }
}

function wsUrl(): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env) return env;
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:8000/ws`;
}

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private refs = new Map<string, number>();
  private chatHandlers = new Map<string, Handler>();
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private ping: ReturnType<typeof setInterval> | null = null;
  private ready = false;
  private stopped = true;

  constructor(private getToken: () => string | null) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.ping) clearInterval(this.ping);
    this.ws?.close();
    this.ws = null;
    this.ready = false;
    useWsStatus.getState().set("closed");
  }

  private connect(): void {
    const token = this.getToken();
    const url = wsUrl();
    if (!token || !url) {
      this.schedule();
      return;
    }
    useWsStatus.getState().set("connecting");
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => {
      let frame: Frame;
      try {
        frame = JSON.parse(ev.data as string) as Frame;
      } catch {
        return;
      }
      if (frame.type === "ready") {
        this.ready = true;
        this.attempt = 0;
        useWsStatus.getState().set("open");
        this.resubscribeAll();
        this.ping = setInterval(() => this.send({ type: "ping" }), 25_000);
        return;
      }
      if (frame.type === "chat.event" && typeof frame.request_id === "string") {
        this.chatHandlers.get(frame.request_id)?.(frame);
        return;
      }
      this.dispatch(frame);
    };
    ws.onclose = () => {
      this.ready = false;
      if (this.ping) clearInterval(this.ping);
      useWsStatus.getState().set("closed");
      if (!this.stopped) this.schedule();
    };
    ws.onerror = () => ws.close();
  }

  private schedule(): void {
    if (this.stopped) return;
    const delay = Math.min(15_000, 500 * 2 ** this.attempt) * (0.5 + Math.random() / 2);
    this.attempt += 1;
    this.timer = setTimeout(() => this.connect(), delay);
  }

  private send(msg: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN && this.ready) this.ws.send(JSON.stringify(msg));
  }

  private dispatch(frame: Frame): void {
    const ch = frame.channel;
    if (!ch) return;
    this.handlers.get(ch)?.forEach((h) => h(frame));
    const wildcard = `${ch.split(":", 1)[0]}:*`;
    this.handlers.get(wildcard)?.forEach((h) => h(frame));
  }

  private specFromKey(key: string): Spec | null {
    const [prefix, rest = ""] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
    if (prefix === "ticks") return { channel: "ticks", symbols: [rest] };
    if (prefix === "orders") return { channel: "orders" };
    if (prefix === "deploy") return { channel: "deployments" };
    if (prefix === "notify") return { channel: "notifications" };
    if (prefix === "backtest") return { channel: "backtest", id: Number(rest) };
    if (prefix === "scanner") return { channel: "scanner", name: rest };
    return null;
  }

  private resubscribeAll(): void {
    const tickSymbols: string[] = [];
    for (const key of this.refs.keys()) {
      if (key.startsWith("ticks:")) tickSymbols.push(key.slice(6));
      else {
        const spec = this.specFromKey(key);
        if (spec) this.send({ type: "subscribe", ...spec });
      }
    }
    if (tickSymbols.length) this.send({ type: "subscribe", channel: "ticks", symbols: tickSymbols });
  }

  subscribe(spec: Spec, handler: Handler): () => void {
    const keys = keysFor(spec);
    const fresh: string[] = [];
    for (const k of keys) {
      if (!this.handlers.has(k)) this.handlers.set(k, new Set());
      this.handlers.get(k)!.add(handler);
      const n = (this.refs.get(k) ?? 0) + 1;
      this.refs.set(k, n);
      if (n === 1) fresh.push(k);
    }
    if (fresh.length) {
      if (spec.channel === "ticks") this.send({ type: "subscribe", channel: "ticks", symbols: fresh.map((k) => k.slice(6)) });
      else this.send({ type: "subscribe", ...spec });
    }
    return () => {
      const gone: string[] = [];
      for (const k of keys) {
        this.handlers.get(k)?.delete(handler);
        const n = (this.refs.get(k) ?? 1) - 1;
        if (n <= 0) {
          this.refs.delete(k);
          this.handlers.delete(k);
          gone.push(k);
        } else this.refs.set(k, n);
      }
      if (gone.length && spec.channel === "ticks") {
        this.send({ type: "unsubscribe", channel: "ticks", symbols: gone.map((k) => k.slice(6)) });
      }
    };
  }

  chat(requestId: string, payload: Record<string, unknown>, handler: Handler): () => void {
    this.chatHandlers.set(requestId, handler);
    this.send({ type: "chat", request_id: requestId, ...payload });
    return () => this.chatHandlers.delete(requestId);
  }
}

let singleton: RealtimeClient | null = null;

export function realtime(getToken?: () => string | null): RealtimeClient {
  if (!singleton) {
    if (!getToken) throw new Error("realtime() first call must provide getToken");
    singleton = new RealtimeClient(getToken);
  }
  return singleton;
}
