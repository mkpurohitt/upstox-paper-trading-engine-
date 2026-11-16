"use client";
import { createApiClient } from "@algo/api-client";
import { useAuth } from "./auth";

export const api = createApiClient({
  getToken: () => useAuth.getState().token,
  onUnauthorized: () => useAuth.getState().refresh(),
});

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

function errorMessage(err: unknown, fallback: string): { message: string; code?: string; details?: unknown } {
  if (err && typeof err === "object") {
    const e = err as { error?: { message?: string; code?: string; details?: unknown }; detail?: unknown };
    if (e.error?.message) return { message: e.error.message, code: e.error.code, details: e.error.details };
    if (typeof e.detail === "string") return { message: e.detail };
  }
  return { message: fallback };
}

/** Unwrap an openapi-fetch result, throwing ApiError on failure. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || !response.ok) {
    const m = errorMessage(error, `Request failed (${response.status})`);
    throw new ApiError(m.message, response.status, m.code, m.details);
  }
  return data as T;
}

/** Untyped escape hatch for streaming (SSE), multipart uploads and file downloads. */
export async function apiFetch(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = useAuth.getState().token;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401 && retry) {
    const fresh = await useAuth.getState().refresh();
    if (fresh) return apiFetch(path, init, false);
  }
  return res;
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await apiFetch(path, { ...init, headers });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const m = errorMessage(body, `Request failed (${res.status})`);
    throw new ApiError(m.message, res.status, m.code, m.details);
  }
  return body as T;
}
