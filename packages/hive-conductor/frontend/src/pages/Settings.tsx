import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPatch } from "../lib/api";
import { PageHeader } from "../components/shared";

type Settings = Record<string, unknown>;

export default function Settings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editVal, setEditVal] = useState("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [elevating, setElevating] = useState(false);
  const [elevPassword, setElevPassword] = useState("");
  const [elevatingFor, setElevatingFor] = useState<string | null>(null);
  const load = useCallback(async () => { try { setSettings(await apiGet<Settings>("/v1/settings")); } catch { /* */ } }, []);
  useEffect(() => { void load(); apiGet<{ models: string[] }>("/v1/settings/models").then((r) => setAvailableModels(r.models)).catch(() => {}); }, [load]);

  async function saveSetting(key: string) {
    if (!settings) return;
    try {
      await apiPatch("/v1/settings", { [key]: parseVal(editVal, settings[key]) });
      setEditing(null);
      await load();
    } catch {
      setElevatingFor(key);
      setElevating(true);
    }
  }

  async function elevateAndSave(key: string) {
    try {
      await fetch("/v1/auth/elevate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ password: elevPassword, permissions: ["config.write"], task_id: `settings-edit-${key}-${Date.now()}` }),
      });
      setElevating(false);
      setElevPassword("");
      await saveSetting(key);
    } catch {
      setElevPassword("");
    }
  }

  function startEdit(key: string) {
    if (!settings) return;
    setEditing(key);
    const v = settings[key];
    setEditVal(typeof v === "object" ? JSON.stringify(v, null, 2) : String(v));
  }

  function parseVal(raw: string, original: unknown): unknown {
    if (typeof original === "boolean") return raw === "true";
    if (typeof original === "number") return Number(raw);
    if (typeof original === "object") { try { return JSON.parse(raw); } catch { return raw; } }
    return raw;
  }

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="System configuration — some changes require admin elevation"
        helpHref="/docs#dashboard"
      />

      {/* Kept unconditionally rather than deleted with the flag (#190). The
          card is a working shortcut to a page that exists for every workspace,
          and "keep the generic branch" would have removed it — which is a
          product call, not the mechanical one that rule is for. */}
      <div className="card" style={{ marginBottom: 16, maxWidth: 480 }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 6 }}>
          Integration tokens (Jira, GitHub, …) are stored encrypted on the server per account.
        </div>
        <Link to="/credentials" className="btn btn-accent" style={{ fontSize: 10, display: "inline-block" }}>
          Manage credentials →
        </Link>
      </div>

      {elevating && elevatingFor && (
        <div className="card" style={{ borderLeft: "3px solid var(--danger)", marginBottom: 12, maxWidth: 400 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--danger)", marginBottom: 6 }}>ELEVATION REQUIRED to edit {elevatingFor}</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input className="input-field" type="password" placeholder="confirm password" value={elevPassword} onChange={(e) => setElevPassword(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void elevateAndSave(elevatingFor); }} />
            <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => void elevateAndSave(elevatingFor)}>elevate</button>
            <button className="btn" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => { setElevating(false); setElevatingFor(null); }}>cancel</button>
          </div>
        </div>
      )}

      {settings ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {Object.entries(settings).map(([key, value]) => (
            <div key={key} style={{ display: "grid", gridTemplateColumns: "200px 1fr auto", gap: 8, padding: "6px 8px", borderBottom: "1px dotted var(--rule)", alignItems: "center" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--accent)" }}>{key}</div>
              {editing === key ? (
                <div style={{ display: "flex", gap: 4 }}>
                  {typeof value === "boolean" ? (
                    <select className="input-field" value={editVal} onChange={(e) => setEditVal(e.target.value)} style={{ width: 80 }}>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  ) : key.toLowerCase().includes("model") && availableModels.length > 0 ? (
                    <select className="input-field" value={editVal} onChange={(e) => setEditVal(e.target.value)}>
                      {!availableModels.includes(editVal) && <option value={editVal}>{editVal}</option>}
                      {availableModels.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  ) : (
                    <input className="input-field" value={editVal} onChange={(e) => setEditVal(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void saveSetting(key); if (e.key === "Escape") setEditing(null); }} />
                  )}
                  <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => void saveSetting(key)}>save</button>
                  <button className="btn" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => setEditing(null)}>cancel</button>
                </div>
              ) : (
                <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink)", cursor: "pointer" }} onClick={() => startEdit(key)} title="click to edit">
                  {typeof value === "boolean" ? (
                    <span style={{ color: value ? "var(--ok)" : "var(--pencil)" }}>{value ? "true" : "false"}</span>
                  ) : typeof value === "number" ? (
                    <span style={{ color: "var(--accent)" }}>{value}</span>
                  ) : typeof value === "object" ? (
                    <pre style={{ margin: 0, fontSize: 9 }}>{JSON.stringify(value, null, 2)}</pre>
                  ) : (
                    String(value)
                  )}
                </div>
              )}
              {editing !== key && (
                <button className="btn" style={{ fontSize: 8, padding: "1px 6px", opacity: 0.6 }} onClick={() => startEdit(key)}>edit</button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>could not load settings</div>
      )}
    </div>
  );
}
