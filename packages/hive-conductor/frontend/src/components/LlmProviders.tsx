import { useEffect, useState } from "react";

interface ProviderRow {
  name: string;
  label: string;
  models: string[];
  test_model: string;
  has_key: boolean;
  activated: boolean;
}

interface ProvidersResponse {
  vault_available: boolean;
  providers: ProviderRow[];
}

// LLM provider keys are deployment-wide vault material (SPEC-072726-3439
// Phase 4): stored via PUT /v1/providers/{name}/key (age vault, never .env),
// activated via POST /v1/providers/{name}/activate — which registers the
// models with LiteLLM and runs a one-token test completion, the install
// journey's "first model call". Both calls need admin (config.write).
export function LlmProviders() {
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = () =>
    fetch("/v1/providers", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then(setData)
      .catch(() => setData(null));

  useEffect(() => {
    load();
  }, []);

  if (!data) return null;

  async function saveKey(name: string) {
    setBusy(name);
    setNotice(null);
    try {
      const r = await fetch(`/v1/providers/${name}/key`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: keys[name] || "" }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
      setKeys((k) => ({ ...k, [name]: "" }));
      setNotice({ kind: "ok", text: `${name}: key stored in the encrypted vault.` });
      await load();
    } catch (e: any) {
      setNotice({ kind: "err", text: `${name}: ${e.message || e}` });
    } finally {
      setBusy(null);
    }
  }

  async function activate(name: string) {
    setBusy(name);
    setNotice(null);
    try {
      const r = await fetch(`/v1/providers/${name}/activate`, {
        method: "POST",
        credentials: "same-origin",
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
      const model = body.first_model_call?.model ?? "";
      setNotice({ kind: "ok", text: `${name}: activated — first model call succeeded on ${model}.` });
      await load();
    } catch (e: any) {
      setNotice({ kind: "err", text: `${name}: ${e.message || e}` });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 14, padding: 12, borderLeft: "3px solid var(--accent)" }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 6 }}>
        LLM PROVIDERS
      </div>
      <div style={{ fontFamily: "var(--hand)", fontSize: 12, lineHeight: 1.4, marginBottom: 10 }}>
        Keys are stored in the encrypted vault (never in .env). Activating registers the models with
        the gateway and runs a one-token test completion — your first model call.
        {!data.vault_available && (
          <span style={{ color: "var(--danger)" }}>
            {" "}Vault unavailable on this host (age toolchain missing) — key storage is disabled.
          </span>
        )}
      </div>
      {notice && (
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 9,
            marginBottom: 8,
            color: notice.kind === "ok" ? "var(--ok)" : "var(--danger)",
          }}
        >
          {notice.text}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {data.providers.map((p) => (
          <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div style={{ fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600, width: 110 }}>
              {p.label}
            </div>
            <input
              type="password"
              placeholder={p.has_key ? "key stored — replace?" : "API key"}
              value={keys[p.name] || ""}
              onChange={(e) => setKeys((k) => ({ ...k, [p.name]: e.target.value }))}
              disabled={!data.vault_available || busy === p.name}
              style={{ flex: 1, minWidth: 160, fontFamily: "var(--mono)", fontSize: 10, padding: "4px 8px" }}
            />
            <button
              className="btn"
              onClick={() => saveKey(p.name)}
              disabled={!data.vault_available || !keys[p.name] || busy === p.name}
              style={{ fontSize: 10, padding: "3px 10px" }}
            >
              Save key
            </button>
            <button
              className="btn-primary"
              onClick={() => activate(p.name)}
              disabled={!p.has_key || busy === p.name}
              style={{ fontSize: 10, padding: "3px 10px" }}
            >
              {busy === p.name ? "…" : p.activated ? "Re-test" : "Activate"}
            </button>
            {p.activated && (
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ok)" }}>● active</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
