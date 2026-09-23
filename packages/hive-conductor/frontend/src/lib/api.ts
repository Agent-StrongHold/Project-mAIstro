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

// A hung request used to leave spinners and empty states up forever: nothing
// in the shared client ever gave up on one (#1423). CRUD calls through this
// client complete in well under this; the two genuinely long-running
// operations (chat streaming, the dashboard assistant) go through their own
// fetch() with their own longer budgets, not this client.
const DEFAULT_TIMEOUT_MS = 30_000;

async function request<T>(
  path: string,
  init: RequestInit,
): Promise<{ data: T; status: number }> {
  const started = performance.now();
  const method = init.method ?? "GET";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
  let r: Response;
  let text: string;
  try {
    r = await fetch(`${API_BASE}${path}`, {
      credentials: "same-origin",
      ...init,
      signal: controller.signal,
    });
    // The timer has to stay armed through reading the body, not just until
    // headers arrive: a server that sends headers promptly and then stalls
    // mid-body leaves fetch() resolved but r.text() still hanging, which
    // the timeout is exactly meant to catch.
    text = await r.text();
  } catch (err) {
    // Anything this try throws (the timeout abort, a dropped connection,
    // offline, CORS) is a transport failure with no HTTP response to read a
    // `detail` from -- so it gets the same human treatment as a bad status
    // (#1436), not a raw `TypeError: Failed to fetch` or `AbortError`.
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    debugApi(method, path, 0, performance.now() - started, timedOut ? "timed out" : err);
    throw new ApiError(
      timedOut
        ? "This took too long and was cancelled. Try again."
        : "Couldn't reach the server. Check your connection and try again.",
      0,
      path,
    );
  } finally {
    clearTimeout(timeout);
  }
  const ms = performance.now() - started;
  let parsed: unknown;
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
