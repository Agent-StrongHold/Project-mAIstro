import { useState, type ReactNode } from "react";
import { useAuthorization } from "../context/AuthorizationContext";

export function ElevationPrompt({
  permission,
  onComplete,
  onCancel,
}: {
  permission: string;
  onComplete?: () => void;
  onCancel?: () => void;
}) {
  const { canElevate, elevate } = useAuthorization();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskId] = useState(() => `ui-elevation-${permission}-${crypto.randomUUID()}`);

  if (!canElevate(permission)) {
    return (
      <div role="status" style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>
        This permission is not assigned to your account. Ask an administrator to grant <strong>{permission}</strong>.
      </div>
    );
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await elevate(permission, taskId, password);
      setPassword("");
      onComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Elevation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ borderLeft: "3px solid var(--accent)", marginTop: 8, maxWidth: 520 }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--accent)", marginBottom: 5 }}>
        SELF-ELEVATION REQUIRED
      </div>
      <div style={{ fontFamily: "var(--hand)", fontSize: 12, marginBottom: 8 }}>
        Your account is assigned <strong>{permission}</strong>. Re-authenticate to use it for this task.
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "end" }}>
        <label style={{ flex: 1, fontFamily: "var(--mono)", fontSize: 9 }}>
          Password
          <input
            className="input-field"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") void submit(); }}
          />
        </label>
        <button className="btn btn-accent" disabled={busy || !password} onClick={() => void submit()}>
          {busy ? "checking..." : "elevate"}
        </button>
        {onCancel && <button className="btn" disabled={busy} onClick={onCancel}>cancel</button>}
      </div>
      {error && <div style={{ color: "var(--danger)", fontFamily: "var(--mono)", fontSize: 9, marginTop: 6 }}>{error}</div>}
    </div>
  );
}

export function AuthorizationNotice({ permission, label }: { permission: string; label: string }) {
  const { can, canElevate } = useAuthorization();
  const [open, setOpen] = useState(false);
  if (can(permission)) return null;
  return (
    <div className="card" style={{ borderLeft: "3px solid var(--danger)", marginBottom: 12, maxWidth: 620 }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--danger)" }}>
        {label} is not currently actionable
      </div>
      <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 4 }}>
        {canElevate(permission)
          ? `This action requires ${permission}. Your account has the grant, but it needs short-lived self-elevation.`
          : `Your account does not have ${permission}. The API will refuse this action; ask an administrator for access.`}
      </div>
      {canElevate(permission) && !open && (
        <button className="btn btn-accent" style={{ marginTop: 8, fontSize: 9 }} onClick={() => setOpen(true)}>
          request elevation
        </button>
      )}
      {open && <ElevationPrompt permission={permission} onComplete={() => setOpen(false)} onCancel={() => setOpen(false)} />}
    </div>
  );
}

export function PermissionBoundary({ permission, children }: { permission: string; children: ReactNode }) {
  const { can, loading } = useAuthorization();
  if (loading) {
    return <div style={{ padding: 24, fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)" }}>checking authorization...</div>;
  }
  if (can(permission)) return <>{children}</>;
  return <AuthorizationNotice permission={permission} label="This surface" />;
}
