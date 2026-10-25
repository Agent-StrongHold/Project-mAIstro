import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiGet, apiPost } from "../lib/api";

export type Capability = {
  assigned: boolean;
  elevated: boolean;
  effective: boolean;
  can_elevate: boolean;
  reason: string;
};

export type AuthorizationSnapshot = {
  version: string;
  role: string;
  assigned_permissions: string[];
  elevated_permissions: string[];
  effective_permissions: string[];
  elevated_tasks: string[];
  elevated_task_expiries: Record<string, string>;
  capabilities: Record<string, Capability>;
  surfaces: Record<string, {
    permission: string | null;
    read_path: string;
    effective: boolean;
    can_elevate: boolean;
  }>;
};

type AuthorizationContextValue = {
  snapshot: AuthorizationSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  can: (permission: string | null | undefined) => boolean;
  canElevate: (permission: string | null | undefined) => boolean;
  surfacePermission: (surface: string) => string | null;
  elevate: (permission: string, taskId: string, password: string) => Promise<void>;
};

const AuthorizationCtx = createContext<AuthorizationContextValue | null>(null);

export function AuthorizationProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<AuthorizationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await apiGet<AuthorizationSnapshot>("/v1/auth/capabilities");
      setSnapshot(next);
      setError(null);
    } catch (err) {
      // A failed refresh keeps the last good snapshot: a background poll that
      // hiccups must not tear the gated surface down (PermissionBoundary
      // renders the notice whenever snapshot is null). The very first load
      // failing still leaves snapshot null, so every gate fails closed.
      setError(err instanceof Error ? err.message : "Could not load authorization");
    } finally {
      // "loading" is the INITIAL load only. The 30s/focus background
      // refreshes must not flip it back: PermissionBoundary unmounts the
      // whole surface while loading, so a refresh that toggled it would
      // collapse and remount the page (dropping its state) twice a minute —
      // the fake-clock polling ladder in rsi-polling-resilience.spec.ts
      // catches exactly that as an extra fresh-mount status poll (#373).
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    const interval = window.setInterval(() => void refresh(), 30_000);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.clearInterval(interval);
    };
  }, [refresh]);

  const value = useMemo<AuthorizationContextValue>(() => ({
    snapshot,
    loading,
    error,
    refresh,
    // All three readers tolerate a snapshot that is null (fetch failed) or
    // shaped by something other than /v1/auth/capabilities (an older backend
    // behind a proxy, a route mock): optional chaining all the way down means
    // the shell fails closed — gated entries hidden, boundaries show the
    // explanation — instead of throwing "Cannot read properties of
    // undefined" into the error boundary and taking every page down (#373).
    can: (permission) => permission == null || Boolean(snapshot?.capabilities?.[permission]?.effective),
    canElevate: (permission) => Boolean(permission && snapshot?.capabilities?.[permission]?.can_elevate),
    surfacePermission: (surface) => snapshot?.surfaces?.[surface]?.permission ?? null,
    elevate: async (permission, taskId, password) => {
      await apiPost("/v1/auth/elevate", { password, permissions: [permission], task_id: taskId });
      await refresh();
    },
  }), [error, loading, refresh, snapshot]);

  return <AuthorizationCtx.Provider value={value}>{children}</AuthorizationCtx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuthorization(): AuthorizationContextValue {
  const value = useContext(AuthorizationCtx);
  if (!value) throw new Error("AuthorizationProvider is not mounted");
  return value;
}
