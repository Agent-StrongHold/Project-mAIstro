import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiError } from "../lib/api";

type ElevationRequest = {
  permission: string;
  resolve: () => void;
  reject: (error: Error) => void;
};

type ElevationContextValue = {
  requestElevation: (permission: string) => Promise<void>;
};

const ElevationContext = createContext<ElevationContextValue | null>(null);

function taskId(permission: string): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `ui-${permission.replace(/[^a-z0-9]+/gi, "-")}-${suffix}`;
}

/** One canonical browser affordance for task-scoped elevation. */
export function ElevationProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<ElevationRequest | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const requestElevation = useCallback((permission: string) => {
    return new Promise<void>((resolve, reject) => {
      setError(null);
      setPassword("");
      setRequest({ permission, resolve, reject });
    });
  }, []);

  async function submit() {
    if (!request || !password) return;
    try {
      const response = await fetch("/v1/auth/elevate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          password,
          permissions: [request.permission],
          task_id: taskId(request.permission),
        }),
      });
      const body = (await response.json()) as { detail?: string };
      if (!response.ok) {
        setError(body.detail || `Elevation failed (${response.status})`);
        return;
      }
      const current = request;
      setRequest(null);
      setPassword("");
      current.resolve();
    } catch {
      setError("Elevation could not be completed. Check the connection and try again.");
    }
  }

  function cancel() {
    if (!request) return;
    const current = request;
    setRequest(null);
    setPassword("");
    current.reject(new Error(`Elevation cancelled for ${current.permission}`));
  }

  return (
    <ElevationContext.Provider value={{ requestElevation }}>
      {children}
      {request && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Permission elevation"
          style={{
            position: "fixed", inset: 0, zIndex: 1000, display: "grid", placeItems: "center",
            background: "rgba(20, 18, 12, 0.42)", padding: 20,
          }}
        >
          <div className="card" style={{ maxWidth: 420, width: "100%", borderLeft: "4px solid var(--accent)" }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--accent)", marginBottom: 8 }}>
              TASK ELEVATION REQUIRED
            </div>
            <p style={{ fontFamily: "var(--hand)", fontSize: 14, margin: "0 0 12px" }}>
              This action needs <strong>{request.permission}</strong>. Confirm with your own account password; elevation is limited to this task.
            </p>
            <input
              autoFocus
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void submit(); }}
              placeholder="Account password"
              aria-label="Account password"
              autoComplete="current-password"
              className="input-field"
            />
            {error && <div style={{ color: "var(--danger)", fontFamily: "var(--mono)", fontSize: 9, marginTop: 8 }}>{error}</div>}
            <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 12 }}>
              <button className="btn" onClick={cancel}>Cancel</button>
              <button className="btn btn-accent" onClick={() => void submit()} disabled={!password}>Elevate for this task</button>
            </div>
          </div>
        </div>
      )}
    </ElevationContext.Provider>
  );
}

export function useElevation() {
  const context = useContext(ElevationContext);
  if (!context) throw new Error("useElevation must be used inside ElevationProvider");
  return context;
}

export function useAuthorizedAction() {
  const context = useContext(ElevationContext);
  if (!context) throw new Error("useAuthorizedAction must be used inside ElevationProvider");
  const { requestElevation } = context;
  return useCallback(async function authorizedAction<T>(
    permission: string,
    action: () => Promise<T>,
  ): Promise<T> {
    try {
      return await action();
    } catch (error) {
      // develop's ApiError carries the backend detail as its human-safe
      // message; the 403 body names the required permission verbatim.
      if (!(error instanceof ApiError) || error.status !== 403 || !error.message.includes(permission)) {
        throw error;
      }
      await requestElevation(permission);
      return action();
    }
  }, [requestElevation]);
}
