import { useEffect, useState } from "react";
import type { LlmProvidersResponse } from "../api/entities";
import { apiGet, apiPost, apiPut } from "../lib/api";
import { SecretField } from "./shared";

export function LlmProviders() {
  const [data, setData] = useState<LlmProvidersResponse | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = () =>
    apiGet<LlmProvidersResponse>("/v1/providers")
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
      await apiPut(`/v1/providers/${name}/key`, { api_key: keys[name] || "" });
      setKeys((k) => ({ ...k, [name]: "" }));
      setNotice({ kind: "ok", text: `${name}: key stored in the encrypted vault.` });
      await load();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setNotice({ kind: "err", text: `${name}: ${message}` });
    } finally {
      setBusy(null);
    }
  }

  async function activate(name: string) {
    setBusy(name);
    setNotice(null);
    try {
      const body = await apiPost<{ first_model_call?: { model?: string } }>(`/v1/providers/${name}/activate`);
      const model = body.first_model_call?.model ?? "";
      setNotice({ kind: "ok", text: `${name}: activated — first model call succeeded on ${model}.` });
      await load();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setNotice({ kind: "err", text: `${name}: ${message}` });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 14, padding: 12, borderLeft: "3px solid var(--accent)" }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 6 }}>
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
            fontSize: 12,
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
            <SecretField
              label={`${p.label} API key`}
              value={keys[p.name] || ""}
              onChange={(next) => setKeys((k) => ({ ...k, [p.name]: next }))}
              stored={p.has_key}
              storedNote={`A key for ${p.label} is already stored. Entering a new one replaces it.`}
              disabled={!data.vault_available || busy === p.name}
              className=""
              style={{ flex: 1, minWidth: 200 }}
            />
            <button
              className="btn"
              onClick={() => saveKey(p.name)}
              disabled={!data.vault_available || !keys[p.name] || busy === p.name}
              style={{ fontSize: 12, padding: "3px 10px" }}
            >
              Save key
            </button>
            <button
              className="btn-primary"
              onClick={() => activate(p.name)}
              disabled={!p.has_key || busy === p.name}
              style={{ fontSize: 12, padding: "3px 10px" }}
            >
              {busy === p.name ? "…" : p.activated ? "Re-test" : "Activate"}
            </button>
            {p.activated && (
              <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ok)" }}>● active</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
