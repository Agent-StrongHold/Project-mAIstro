import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPut } from "../lib/api";
import { LlmProviders } from "../components/LlmProviders";
import { PageHeader } from "../components/shared";

type ConfigField = {
  name: string;
  label: string;
  placeholder: string;
  required: boolean;
};

type CredentialRow = {
  id: string;
  label: string;
  description: string;
  help_url: string;
  placeholder: string;
  configured: boolean;
  updated_at?: string | null;
  config_fields?: ConfigField[];
  config_values?: Record<string, string>;
};

export default function Credentials() {
  const [rows, setRows] = useState<CredentialRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  // task #27: per-provider config drafts (e.g. Airtable base_id).
  // Shape: { providerId: { field_name: value } }
  const [configDrafts, setConfigDrafts] = useState<
    Record<string, Record<string, string>>
  >({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<{ credentials: CredentialRow[] }>("/v1/credentials");
      setRows(data.credentials);
      // Hydrate config drafts from server-persisted config_values
      const init: Record<string, Record<string, string>> = {};
      for (const row of data.credentials) {
        if (row.config_fields?.length) {
          init[row.id] = { ...(row.config_values ?? {}) };
        }
      }
      setConfigDrafts(init);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load credentials");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(providerId: string) {
    const secret = drafts[providerId]?.trim();
    if (!secret) return;
    setSaving(providerId);
    setError(null);
    setMessage(null);
    try {
      await apiPut(`/v1/credentials/${providerId}`, { secret });
      setDrafts((d) => ({ ...d, [providerId]: "" }));
      setMessage(`${providerId} saved securely`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(null);
    }
  }

  async function saveConfig(providerId: string) {
    const config = configDrafts[providerId] ?? {};
    setSaving(providerId);
    setError(null);
    setMessage(null);
    try {
      await apiPut(`/v1/credentials/${providerId}/config`, { config });
      setMessage(`${providerId} config saved`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(null);
    }
  }

  async function remove(providerId: string) {
    setSaving(providerId);
    setError(null);
    try {
      await apiDelete(`/v1/credentials/${providerId}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setSaving(null);
    }
  }

  return (
    <div style={{ padding: "20px 24px", maxWidth: 720 }}>
      <PageHeader
        title="Integration credentials"
        subtitle="Encrypted at rest in this container — used by Hive agents and MCP at runtime. Never sent back to the browser."
      />

      <LlmProviders />

      <div className="card" style={{ marginBottom: 14, padding: 12, borderLeft: "3px solid var(--accent)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 6 }}>
          CONTAINER RUNTIME
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, lineHeight: 1.4 }}>
          Configure <strong>Jira</strong>, <strong>Confluence</strong>, and <strong>Atlassian Rovo MCP</strong> tokens here
          for headless agent and MCP calls in this sandbox. Launch may also inject{" "}
          <code style={{ fontFamily: "var(--mono)", fontSize: 10 }}>ATLASSIAN_API_TOKEN</code> /{" "}
          <code style={{ fontFamily: "var(--mono)", fontSize: 10 }}>ATLASSIAN_SITE_URL</code> at deploy time.
          Cursor OAuth is optional for local template development only.
        </div>
      </div>

      {error && (
        <div className="card" style={{ borderLeft: "3px solid var(--danger)", marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--danger)" }}>{error}</div>
        </div>
      )}
      {message && (
        <div className="card" style={{ borderLeft: "3px solid var(--ok)", marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ok)" }}>{message}</div>
        </div>
      )}

      {loading ? (
        <div style={{ fontFamily: "var(--hand)", color: "var(--pencil)" }}>Loading…</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rows.map((row) => (
            <article key={row.id} className="card" style={{ padding: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                <div>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600 }}>{row.label}</div>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 4 }}>
                    {row.description}
                  </div>
                </div>
                <span
                  className="hex-badge"
                  style={{
                    background: row.configured ? "var(--ok)" : "var(--rule)",
                    color: row.configured ? "var(--paper)" : "var(--pencil)",
                    fontSize: 8,
                  }}
                >
                  {row.configured ? "configured" : "missing"}
                </span>
              </div>

              <a
                href={row.help_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 9,
                  color: "var(--accent)",
                  marginTop: 8,
                  display: "inline-block",
                }}
              >
                Create or manage token ↗
              </a>

              <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  className="input-field"
                  type="password"
                  placeholder={row.placeholder || "Paste token here"}
                  value={drafts[row.id] ?? ""}
                  onChange={(e) => setDrafts((d) => ({ ...d, [row.id]: e.target.value }))}
                  autoComplete="off"
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="btn btn-accent"
                  disabled={saving === row.id || !drafts[row.id]?.trim()}
                  onClick={() => void save(row.id)}
                  style={{ fontSize: 9 }}
                >
                  {saving === row.id ? "saving…" : "save"}
                </button>
                {row.configured && (
                  <button
                    type="button"
                    className="btn"
                    disabled={saving === row.id}
                    onClick={() => void remove(row.id)}
                    style={{ fontSize: 9 }}
                  >
                    remove
                  </button>
                )}
              </div>

              {row.config_fields && row.config_fields.length > 0 && (
                <div
                  style={{
                    marginTop: 12,
                    paddingTop: 10,
                    borderTop: "1px dashed var(--rule)",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 8,
                      color: "var(--pencil)",
                      marginBottom: 6,
                    }}
                  >
                    Provider config (non-secret)
                  </div>
                  {row.config_fields.map((f) => (
                    <div
                      key={f.name}
                      style={{
                        display: "flex",
                        gap: 8,
                        alignItems: "center",
                        marginBottom: 6,
                      }}
                    >
                      <label
                        style={{
                          fontFamily: "var(--hand)",
                          fontSize: 11,
                          minWidth: 110,
                          color: "var(--ink)",
                        }}
                      >
                        {f.label}
                        {f.required && (
                          <span style={{ color: "var(--danger)" }}> *</span>
                        )}
                      </label>
                      <input
                        className="input-field"
                        type="text"
                        placeholder={f.placeholder}
                        value={
                          configDrafts[row.id]?.[f.name] ??
                          row.config_values?.[f.name] ??
                          ""
                        }
                        onChange={(e) =>
                          setConfigDrafts((cd) => ({
                            ...cd,
                            [row.id]: {
                              ...(cd[row.id] ?? row.config_values ?? {}),
                              [f.name]: e.target.value,
                            },
                          }))
                        }
                        style={{ flex: 1 }}
                      />
                    </div>
                  ))}
                  <button
                    type="button"
                    className="btn"
                    disabled={saving === row.id}
                    onClick={() => void saveConfig(row.id)}
                    style={{ fontSize: 9, marginTop: 4 }}
                  >
                    {saving === row.id ? "saving…" : "save config"}
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
