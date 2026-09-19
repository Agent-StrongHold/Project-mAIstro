/** Relative API base (Vite proxies /v1 and /health in dev). */
import { debugApi } from "./debug";

export const API_BASE = "";

/** Thrown by a failed request. `message` is human copy safe to show a user
 * (#1436); `status`/`path` carry the raw transport detail for developer
 * diagnostics (also already logged to the console by `debugApi`) without
 * putting it in front of someone who can't act on a route string. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function fallbackMessage(status: number): string {
  if (status === 401) return "You're not signed in, or your session expired. Sign in again to continue.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 404) return "That couldn't be found. It may have been moved or removed.";
  if (status === 429) return "Too many requests right now. Wait a moment and try again.";
  if (status >= 500) return "Something went wrong on the server. Try again in a moment.";
  return "The request couldn't be completed. Try again.";
}

async function request<T>(
  path: string,
  init: RequestInit,
): Promise<{ data: T; status: number }> {
  const started = performance.now();
  const method = init.method ?? "GET";
  const r = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
  });
  const ms = performance.now() - started;
  let parsed: unknown;
  const text = await r.text();
  if (text && r.status !== 204) {
    try {
      parsed = JSON.parse(text) as T;
    } catch {
      parsed = text;
    }
  }
  debugApi(method, path, r.status, ms, r.ok ? undefined : parsed);
  if (!r.ok) {
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : undefined;
    throw new ApiError(detail || fallbackMessage(r.status), r.status, path);
  }
  return { data: parsed as T, status: r.status };
}

export async function apiGet<T>(path: string): Promise<T> {
  const { data } = await request<T>(path, { method: "GET" });
  return data;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const { data, status } = await request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (status === 204) return undefined as T;
  return data;
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const { data, status } = await request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (status === 204) return undefined as T;
  return data;
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  const { data, status } = await request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (status === 204) return undefined as T;
  return data;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const { data, status } = await request<T>(path, { method: "DELETE" });
  if (status === 204) return undefined as T;
  return data;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { data } = await request<T>(path, init ?? {});
  return data;
}
