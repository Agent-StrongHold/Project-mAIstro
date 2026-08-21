/** Relative API base (Vite proxies /v1 and /health in dev). */
import { debugApi } from "./debug";

export const API_BASE = "";

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
        : `${r.status}`;
    throw new Error(`${path}: ${detail}`);
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
