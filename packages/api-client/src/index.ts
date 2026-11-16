/**
 * Typed AlgoDesk API client.
 *
 * `schema.d.ts` is generated from the FastAPI OpenAPI document with
 * `pnpm gen:api` (see package.json). Every request/response is type-checked
 * against the backend's Pydantic models.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];

export interface ClientOptions {
  baseUrl?: string;
  getToken: () => string | null;
  /** Called on 401; should try to refresh and return a fresh token (or null). */
  onUnauthorized?: () => Promise<string | null>;
}

export function createApiClient(opts: ClientOptions) {
  const client = createClient<paths>({ baseUrl: opts.baseUrl ?? "", credentials: "include" });
  const retried = new WeakSet<Request>();

  const auth: Middleware = {
    async onRequest({ request }) {
      const token = opts.getToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
    async onResponse({ request, response }) {
      if (response.status !== 401 || !opts.onUnauthorized || retried.has(request)) return response;
      const fresh = await opts.onUnauthorized();
      if (!fresh) return response;
      const retry = new Request(request, { headers: new Headers(request.headers) });
      retry.headers.set("Authorization", `Bearer ${fresh}`);
      retried.add(retry);
      return fetch(retry);
    },
  };
  client.use(auth);
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;
