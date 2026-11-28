import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiError } from "../lib/api";
import { elevateTask, type ElevationContextValue, type ElevationRequest } from "../lib/elevation";
import { SecretField } from "./shared";

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
      await elevateTask(password, request.permission, taskId(request.permission));
      const current = request;
      setRequest(null);
      setPassword("");
      current.resolve();
    } catch (error) {
      // The shared client already turned the outcome into human copy: the
      // backend's verbatim detail for a refusal ("Invalid password", the
      // unassigned-permission cause), transport copy when unreachable (#1436).
      setError(
        error instanceof Error
          ? error.message
          : "Elevation could not be completed. Check the connection and try again.",
      );
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
            <SecretField
              label="Account password"
              autoFocus
              value={password}
              onChange={setPassword}
              onKeyDown={(event) => { if (event.key === "Enter") void submit(); }}
              autoComplete="current-password"
              style={{ marginBottom: 8 }}
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
