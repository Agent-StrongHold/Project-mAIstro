import { useEffect, useState } from "react";
import { apiGet, fallbackMessage, ApiError } from "../lib/api";
import { SecretField, TextField } from "../components/shared";

type Preset = { name: string; label: string; description: string; max_vcpu: number; max_memory_gb: number; db_backend: string; networking: string; gpu_available: boolean; reactor_enabled: boolean; max_agents: number };

type IdentityStatus = "checking" | "operational" | "disabled" | "misconfigured" | "unavailable";

// Gateway model-discovery lifecycle (#287): "pending" while the catalog fetch
// is in flight, "ok" once the gateway answered with a non-empty, well-formed
// catalog, "failed" for every distinguishable failure (auth, not found,
// gateway error, network, malformed, empty). A failed check keeps the curated
// list usable for offline setup, but it must never be presented as
// successfully discovered gateway state.
type ModelCheck = "pending" | "ok" | "failed";

const MODULES = [
  { id: "crypto_identity", name: "Crypto Identity", desc: "BIP39 HD wallet seed, DID addresses, hierarchical key derivation, agent signing (ADR-021/024)", requires: [] },
  { id: "crypto_trading", name: "Crypto Trading", desc: "CoinSwarm integration, exchange WebSockets, evolutionary strategies", requires: ["crypto_identity"] },
  { id: "lightning", name: "Lightning Federation", desc: "LND node, Lightning Address, conductor-to-conductor payments (ADR-027)", requires: ["crypto_identity"] },
  { id: "home_automation", name: "Home Automation", desc: "Home Assistant MCP control, IoT device management", requires: [] },
  { id: "browser_agent", name: "Browser Agent", desc: "Camoufox browser automation, email reader, web scraping", requires: [] },
  { id: "red_team", name: "Red Team + Stress Rehearsal", desc: "Weekly self-hardening security scans, chaos testing", requires: [] },
  { id: "dream_loop", name: "Dream Loop", desc: "Idle-time memory consolidation, autonomous learning cycles", requires: [] },
  { id: "skill_forge", name: "Skill Forge", desc: "Self-authoring skills, AI builder wizard, Warden security scanning", requires: [] },
];

export default function Setup() {
  const [step, setStep] = useState(0);
  const [conductorName, setConductorName] = useState("Hive Conductor");
  const [routerModel, setRouterModel] = useState("gemini-3.1-flash-lite");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [preset, setPreset] = useState<string | null>(null);
  const [presets, setPresets] = useState<Record<string, Preset>>({});
  const [presetsUnavailable, setPresetsUnavailable] = useState(false);
  const [identityStatus, setIdentityStatus] = useState<IdentityStatus>("checking");
  const [identityReason, setIdentityReason] = useState<string | null>(null);
  const [modules, setModules] = useState<string[]>([]);
  const [adminUsername, setAdminUsername] = useState("admin");
  const [adminPassword, setAdminPassword] = useState("");
  const [userUsername, setUserUsername] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mnemonic, setMnemonic] = useState<string[] | null>(null);
  const [didKey, setDidKey] = useState<string | null>(null);
  const [mnemonicConfirmed, setMnemonicConfirmed] = useState(false);
  const [modelCheck, setModelCheck] = useState<ModelCheck>("pending");
  const [modelError, setModelError] = useState<string | null>(null);
  const [modelErrorKind, setModelErrorKind] = useState<string | null>(null);
  const [fallbackAcknowledged, setFallbackAcknowledged] = useState(false);
  const [manualModel, setManualModel] = useState(false);
  const [fetchKey, setFetchKey] = useState(0);

  const steps = ["Hive", "Hardware", "Accounts", "Modules", "Confirm"];

  // Load available models from the LLM gateway via Hive's
  // /v1/settings/models proxy. The user's LITELLM key stays server-side.
  // Setup runs BEFORE any login, so the auth-gated /v1/settings/models will
  // 401: the curated list below is only ever a baseline for offline setup,
  // and a failed fetch keeps it explicitly marked unverified (#287) instead
  // of passing it off as discovered gateway state. After the admin user
  // finishes setup, settings can refresh the list from the live gateway.
  useEffect(() => {
    // Curated LLM gateway model aliases — sorted by "good router default"
    // first (small, fast, cheap), then by family. Trim / extend as the
    // gateway's catalog evolves.
    const FALLBACK_MODELS = [
      // Routers (small / fast / cheap — ideal default)
      "gemini-3.1-flash-lite",
      "gemini-3.5-flash-lite",
      "claude-haiku-4-5",
      "gpt-4.1-nano",
      "gpt-5-nano",
      // Mid-tier
      "claude-sonnet-4-5",
      "claude-sonnet-4-6",
      "gemini-3.5-flash",
      "gemini-3.5-flash",
      "gpt-4o-mini",
      "gpt-4.1-mini",
      "gpt-5-mini",
      // Heavy reasoning (overkill for router)
      "claude-opus-4-5",
      "claude-opus-4-6",
      "claude-opus-4-7",
      "gpt-5",
      "gpt-5.1",
      "gpt-5.2",
      "gemini-3.5-pro",
      "o3",
      "o3-pro",
      // Embedding (won't actually work as router, surfaced for completeness)
      "text-embedding-3",
    ];
    setAvailableModels(FALLBACK_MODELS);
    setRouterModel((cur) =>
      FALLBACK_MODELS.includes(cur) ? cur : "gemini-3.1-flash-lite",
    );

    // Best-effort: ask the live gateway for the real catalog and replace the
    // curated baseline only on a well-formed, non-empty answer (#287). Every
    // failure path keeps the curated list usable but records WHY the gateway
    // state is not trustworthy: modelCheck stays "failed" with an actionable,
    // per-cause message, so the UI can demand an explicit
    // unverified-availability acknowledgement and offer a retry instead of
    // silently marking gateway/model setup complete after a failed fetch.
    function failDiscovery(kind: string, message: string) {
      setModelCheck("failed");
      setModelErrorKind(kind);
      setModelError(message);
    }
    let active = true;
    setModelsLoading(true);
    setModelCheck("pending");
    setModelError(null);
    setModelErrorKind(null);
    apiGet<{ models: unknown }>("/v1/settings/models")
      .then((data) => {
        if (!active) return;
        // A malformed payload is its own failure class, not an empty catalog:
        // only an array of non-empty strings counts as a catalog.
        if (!Array.isArray(data.models)) {
          failDiscovery("malformed", "The gateway response could not be parsed as a model catalog. Check the gateway deployment.");
          return;
        }
        const models = data.models.filter((m): m is string => typeof m === "string" && m.trim().length > 0);
        if (models.length === 0) {
          failDiscovery("empty", "The gateway answered but returned an empty model catalog. Nothing is confirmed available; the list below is curated suggestions.");
          return;
        }
        setAvailableModels(models);
        setRouterModel((cur) =>
          models.includes(cur)
            ? cur
            : models.find((m) => m === "gemini-3.1-flash-lite") ??
              models.find((m) => m.startsWith("gemini-") && m.includes("flash")) ??
              models[0],
        );
        setModelCheck("ok");
        setModelError(null);
        setModelErrorKind(null);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError) {
          // Distinguishable causes (#287): auth, missing endpoint, gateway
          // outage, connectivity/timeout, other. The copy says what to do,
          // not just what broke; raw statuses stay in the console via debugApi.
          if (err.status === 401 || err.status === 403) {
            failDiscovery("auth", "Gateway authentication failed. During setup there is no signed-in session, so the gateway catalog could not be queried — model availability below is unverified.");
          } else if (err.status === 404) {
            failDiscovery("not_found", "The gateway model-discovery endpoint was not found (404). Check the configured gateway URL.");
          } else if (err.status >= 500) {
            failDiscovery("server", `The gateway reported a server error (HTTP ${err.status}). It may be misconfigured or overloaded — retry, and fix the gateway if it persists.`);
          } else if (err.status === 0) {
            failDiscovery("network", "Could not reach the gateway to discover models (network error or timeout). Check connectivity and proxy settings.");
          } else {
            failDiscovery("http", `The gateway rejected the model-discovery request (HTTP ${err.status}).`);
          }
        } else {
          failDiscovery("unexpected", "An unexpected error occurred while discovering gateway models.");
        }
      })
      .finally(() => {
        if (active) setModelsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [fetchKey]);

  useEffect(() => {
    let active = true;
    apiGet<{ identity?: { status?: string; reason?: string } }>("/health")
      .then((data) => {
        if (!active) return;
        const status = data.identity?.status;
        setIdentityReason(data.identity?.reason ?? null);
        if (status === "operational" || status === "disabled" || status === "misconfigured" || status === "unavailable") {
          setIdentityStatus(status);
        } else {
          setIdentityStatus("unavailable");
        }
      })
      .catch(() => {
        // Do not offer a crypto action when the capability probe did not answer.
        if (active) {
          setIdentityStatus("unavailable");
          setIdentityReason("health_probe_failed");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  // Mount-only, and it has to stay that way. This was previously a bare
  // `void loadPresets()` sitting in the component body, which re-ran on every
  // render: the fetch resolved, setPresets stored a freshly-allocated object
  // (never Object.is-equal, so React could not bail out), that re-rendered, and
  // the call fired again — an unbounded request loop against
  // /v1/setup/presets. It hammered the server for as long as the wizard was
  // open and kept the page from ever settling, which is what made all 12
  // Playwright specs in hive-conductor-e2e-ui time out at exactly 60s.
  useEffect(() => {
    let active = true;
    apiGet<{ presets: Record<string, Preset> }>("/v1/setup/presets")
      .then((data) => {
        if (active) setPresets(data.presets);
      })
      .catch(() => {
        // Pre-login 401 is expected here, so an empty `presets` is a normal
        // state rather than only a failure — which is exactly why the Hardware
        // step must not hard-require a selection. Flagged so the step can say
        // what happened instead of rendering an empty list with a dead Next
        // button (#129).
        if (active) setPresetsUnavailable(true);
      });
    return () => {
      active = false;
    };
  }, []);

  async function finish() {
    setLoading(true);
    setError(null);
    try {
      // Final preflight (#287): re-query the gateway for the effective
      // default model right before setup completes. "verified" requires the
      // gateway to answer AND list the chosen model; any failure — or a
      // catalog that lacks the model — completes as explicitly "unverified",
      // recorded server-side with the setup configuration, instead of a
      // failed fetch silently passing for a valid gateway catalog.
      let modelAvailability: "verified" | "unverified" = "unverified";
      try {
        const check = await apiGet<{ models: unknown }>("/v1/settings/models");
        const models = Array.isArray(check.models)
          ? check.models.filter((m): m is string => typeof m === "string" && m.trim().length > 0)
          : [];
        if (models.includes(routerModel)) modelAvailability = "verified";
      } catch {
        modelAvailability = "unverified";
      }
      const res = await fetch("/v1/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conductor_name: conductorName,
          default_model: routerModel,
          model_availability: modelAvailability,
          hardware_preset: preset,
          optional_modules: modules,
          admin_username: adminUsername,
          admin_password: adminPassword,
          user_username: userUsername,
          user_password: userPassword,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? fallbackMessage(res.status));
      }
      const data = await res.json();
      if (data.mnemonic) {
        setMnemonic(data.mnemonic);
        setDidKey(data.config?.user_did ?? null);
      } else {
        await autoLogin();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "setup failed");
    } finally {
      setLoading(false);
    }
  }

  async function autoLogin() {
    const r = await fetch("/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: userUsername, password: userPassword }),
    });
    if (!r.ok) throw new Error("auto-login failed");
    // When Hive is served behind the maistro gateway at a sub-path,
    // redirecting to "/" dumps the user at the maistro catalog with no obvious
    // way back. Use the Vite base path so they land on the app index, which
    // redirects to the dashboard.
    window.location.href = import.meta.env.BASE_URL || "/";
  }

  if (mnemonic) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e9e3d3", padding: 20 }}>
        <div style={{ width: "100%", maxWidth: 520, background: "var(--paper)", border: "2px solid var(--ink)", borderRadius: 8 }}>
          <div style={{ padding: "16px 20px", borderBottom: "2px solid var(--ink)", background: "rgba(196,69,42,0.08)" }}>
            <div style={{ fontFamily: "var(--hand)", fontSize: 22, fontWeight: 700, color: "var(--danger)" }}>Recovery Seed Phrase</div>
            <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--danger)", marginTop: 4 }}>WRITE THESE DOWN. They will never be shown again. This is the root of trust for your hive.</div>
          </div>
          <div style={{ padding: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 }}>
              {mnemonic.map((word, i) => (
                <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 12, padding: "4px 6px", border: "1px solid var(--rule)", borderRadius: 3, display: "flex", gap: 4 }}>
                  <span style={{ color: "var(--pencil)", fontSize: 12 }}>{i + 1}.</span> {word}
                </div>
              ))}
            </div>
            {didKey && (
              <div style={{ marginTop: 12, padding: "6px 8px", background: "var(--honey-light)", borderRadius: 4, fontFamily: "var(--mono)", fontSize: 12, wordBreak: "break-all" }}>
                <span style={{ color: "var(--pencil)" }}>DID:</span> {didKey}
              </div>
            )}
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={mnemonicConfirmed} onChange={(e) => setMnemonicConfirmed(e.target.checked)} id="mnemonic-check" />
              <label htmlFor="mnemonic-check" style={{ fontFamily: "var(--hand)", fontSize: 13, cursor: "pointer" }}>I have written these words down and stored them safely</label>
            </div>
          </div>
          <div style={{ padding: "12px 20px", borderTop: "1px solid var(--rule)", display: "flex", justifyContent: "flex-end" }}>
            <button className="btn btn-accent" disabled={!mnemonicConfirmed} onClick={() => void autoLogin()}>enter the hive {"\uD83D\uDC1D"}</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e9e3d3", padding: 20 }}>
      <div style={{ width: "100%", maxWidth: 560, background: "var(--paper)", border: "2px solid var(--ink)", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "2px solid var(--ink)", background: "var(--honey-light)" }}>
          <div style={{ fontFamily: "var(--hand)", fontSize: 30, fontWeight: 700 }}>
            {"\uD83D\uDC1D"} Hive Conductor
          </div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 14, color: "var(--pencil)", marginTop: 2 }}>
            First boot — configure your hive before the swarm can work
          </div>
        </div>

        <div style={{ display: "flex", borderBottom: "1px solid var(--rule)" }}>
          {steps.map((s, i) => (
            <div key={s} style={{ flex: 1, padding: "8px 0", textAlign: "center", fontFamily: "var(--mono)", fontSize: 12, cursor: "pointer", borderBottom: step === i ? "2px solid var(--accent)" : "2px solid transparent", color: step === i ? "var(--ink)" : i < step ? "var(--ok)" : "var(--pencil)", fontWeight: step === i ? 700 : 400 }} onClick={() => { if (i < step) setStep(i); }}>
              <div style={{ width: 18, height: 18, borderRadius: "50%", border: `1.3px solid ${i <= step ? "var(--accent)" : "var(--rule)"}`, background: i < step ? "var(--accent)" : "transparent", color: i < step ? "var(--paper)" : "var(--pencil)", margin: "0 auto 3px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>
                {i < step ? "\u2713" : i + 1}
              </div>
              {s}
            </div>
          ))}
        </div>

        <div style={{ padding: "16px 20px", minHeight: 240 }}>
          {error && <div style={{ padding: "6px 10px", background: "rgba(196,69,42,0.12)", border: "1px solid var(--danger)", borderRadius: 4, fontFamily: "var(--mono)", fontSize: 12, color: "var(--danger)", marginBottom: 10 }}>{error}</div>}

          {step === 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600 }}>
                Name your hive
              </div>
              <TextField label="Conductor name" value={conductorName} onChange={setConductorName} placeholder="Hive Conductor" />
              <div>
                {/* One label for whichever control this branch renders, so the
                    field keeps its name when the models list arrives and the
                    <input> becomes a <select> (#375). */}
                <label htmlFor="setup-router-model" style={{ display: "block", fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 3 }}>Router model</label>
                {manualModel || availableModels.length === 0 ? (
                  <input
                    id="setup-router-model"
                    className="input-field"
                    placeholder={modelsLoading ? "Loading models from gateway…" : "gemini-3.1-flash-lite"}
                    value={routerModel}
                    onChange={(e) => setRouterModel(e.target.value)}
                    disabled={modelsLoading}
                  />
                ) : (
                  <select
                    id="setup-router-model"
                    className="input-field"
                    value={routerModel}
                    onChange={(e) => setRouterModel(e.target.value)}
                    style={{ width: "100%" }}
                  >
                    {availableModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                )}
                {availableModels.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {manualModel ? (
                      <button type="button" className="btn" data-testid="model-list-toggle" onClick={() => { setManualModel(false); setFallbackAcknowledged(false); }}>Pick from the model list instead</button>
                    ) : (
                      <button type="button" className="btn" data-testid="model-manual-toggle" onClick={() => { setManualModel(true); setFallbackAcknowledged(false); }}>Enter a model ID manually</button>
                    )}
                  </div>
                )}
                {/* Discovery provenance (#287): the wizard must never blur a
                    real gateway catalog into curated suggestions or manual
                    entry — each renders with its own status line, and only
                    the discovered state counts as verified. */}
                <div data-testid="model-discovery-status" style={{ fontFamily: "var(--mono)", fontSize: 12, marginTop: 6, color: modelCheck === "ok" && !manualModel ? "var(--ok)" : "var(--pencil)" }}>
                  {modelCheck === "pending" && !manualModel && "Checking the gateway model catalog…"}
                  {modelCheck === "ok" && !manualModel && `✓ ${availableModels.length} models discovered from the gateway`}
                  {modelCheck === "failed" && !manualModel && "Curated suggestions — the gateway was not queried successfully, availability is UNVERIFIED"}
                  {manualModel && "Manual entry — the gateway has not confirmed this ID; availability is UNVERIFIED"}
                </div>
                {modelError && (
                  <div role="alert" data-testid={`model-error-${modelErrorKind ?? "unknown"}`} style={{ padding: "6px 10px", background: "rgba(196,69,42,0.12)", border: "1px solid var(--danger)", borderRadius: 4, fontFamily: "var(--mono)", fontSize: 12, color: "var(--danger)" }}>
                    <div>{modelError}</div>
                    <button type="button" className="btn" data-testid="model-retry" style={{ marginTop: 6 }} disabled={modelsLoading} onClick={() => setFetchKey((k) => k + 1)}>Retry gateway discovery</button>
                  </div>
                )}
                {(modelCheck === "failed" || manualModel) && (
                  <div data-testid="unverified-ack" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                    <input type="checkbox" id="unverified-model-ack" checked={fallbackAcknowledged} onChange={(e) => setFallbackAcknowledged(e.target.checked)} />
                    <label htmlFor="unverified-model-ack" style={{ fontFamily: "var(--hand)", fontSize: 13, cursor: "pointer" }}>I understand the gateway has not confirmed this model and availability is unverified.</label>
                  </div>
                )}
                <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 4 }}>
                  The queen bee's brain — classifies intent, complexity, and cost to route each request to the best worker model. Needs to be fast and cheap, not the strongest. <code>gemini-3.1-flash-lite</code> is a good default.{" "}
                  <a
                    href="https://latest.llm-gateway-admin.example.com/ui/?page=model-hub"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "var(--accent)", textDecoration: "underline" }}
                  >
                    Browse the MAISTRO Model Hub →
                  </a>{" "}
                  for details on each model (context window, pricing, capabilities).
                </div>
              </div>
            </div>
          )}

          {step === 1 && (
            <div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Pick your hardware tier</div>
              {Object.keys(presets).length === 0 && (
                <div className="card" style={{ marginBottom: 10, borderLeft: "3px solid var(--pencil)" }}>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 6 }}>
                    {presetsUnavailable ? "HARDWARE PROFILES UNAVAILABLE" : "LOADING HARDWARE PROFILES"}
                  </div>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 12, lineHeight: 1.4 }}>
                    {presetsUnavailable
                      ? "Could not load the hardware profiles — this endpoint requires a session, and setup runs before login. You can continue; the server applies its own default."
                      : "Fetching available profiles…"}
                  </div>
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {Object.values(presets).map((p) => (
                  <div key={p.name} onClick={() => setPreset(p.name)} style={{ padding: 10, border: `1.4px solid ${preset === p.name ? "var(--accent)" : "var(--ink)"}`, borderRadius: 6, cursor: "pointer", background: preset === p.name ? "var(--honey-light)" : "transparent" }}>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 17, fontWeight: 600, color: preset === p.name ? "var(--accent)" : "var(--ink)" }}>{p.label}</div>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "3px 0" }}>{p.description}</div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>{p.max_vcpu} vCPU · {p.max_memory_gb}GB · {p.db_backend} · {p.max_agents} agents{p.gpu_available ? " · GPU" : ""}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {step === 2 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600 }}>Create user accounts</div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 13, color: "var(--pencil)" }}>
                <strong style={{ color: "var(--danger)" }}>Admin</strong> = break-glass superuser. Blocked from chat. Blocked from fun features without debug mode. Use it only when something is broken.
                <br /><br />
                <strong style={{ color: "var(--accent)" }}>User</strong> = your daily driver. Full access to chat, agents, missions — everything you actually use.
              </div>
              <div className="card" style={{ borderLeft: "3px solid var(--danger)" }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--danger)", marginBottom: 6 }}>ADMIN (BREAK-GLASS)</div>
                {/* Both password fields on this step were named "password" and
                    nothing else, one for each account -- identical to anything
                    that cannot see which card they sit in (#375). */}
                <div style={{ display: "flex", gap: 8 }}>
                  <TextField label="Admin username" value={adminUsername} onChange={setAdminUsername} autoComplete="username" required style={{ flex: 1 }} />
                  <SecretField label="Admin password" value={adminPassword} onChange={setAdminPassword} autoComplete="new-password" required style={{ flex: 1 }} />
                </div>
              </div>
              <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--accent)", marginBottom: 6 }}>DAILY USER</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <TextField label="Daily user username" value={userUsername} onChange={setUserUsername} autoComplete="username" required style={{ flex: 1 }} />
                  <SecretField label="Daily user password" value={userPassword} onChange={setUserPassword} autoComplete="new-password" required style={{ flex: 1 }} />
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600 }}>Optional modules</div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 13, color: "var(--pencil)" }}>Enable now or later from Settings. Crypto Identity enables the BIP39 HD derivation tree.</div>
              {MODULES.map((m) => {
                const enabled = modules.includes(m.id);
                const depsMet = m.requires.every((r) => modules.includes(r));
                const identityUnavailable =
                  m.id === "crypto_identity" &&
                  (identityStatus === "checking" ||
                    identityStatus === "unavailable" ||
                    (identityStatus === "misconfigured" && identityReason !== "setup_incomplete"));
                return (
                  <div key={m.id} className="card" style={{ display: "grid", gridTemplateColumns: "1fr 36px", gap: 8, alignItems: "center", opacity: identityUnavailable ? 0.5 : depsMet || enabled ? 1 : 0.5 }}>
                    <div>
                      <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>{m.name}</div>
                      <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)" }}>{m.desc}</div>
                      {m.requires.length > 0 && <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginTop: 2 }}>requires: {m.requires.join(", ")}</div>}
                      {identityUnavailable && <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--danger)", marginTop: 2 }}>{identityStatus === "checking" ? "checking deployment support; action unavailable" : "unavailable in this deployment; no action offered"}</div>}
                    </div>
                    <button
                      type="button"
                      className={`toggle${enabled ? " on" : ""}`}
                      aria-label={`Toggle ${m.name}`}
                      disabled={identityUnavailable || !(depsMet || enabled)}
                      onClick={() => setModules(enabled ? modules.filter((x) => x !== m.id) : [...modules, m.id])}
                    />
                  </div>
                );
              })}
            </div>
          )}

          {step === 4 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600 }}>Confirm configuration</div>
              <div className="card">
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 4 }}>HIVE</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{conductorName}</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginTop: 2 }}>
                  router: {routerModel}
                  {(manualModel || modelCheck === "failed") && (
                    <span data-testid="router-model-unverified" style={{ color: "var(--danger)" }}> · unverified</span>
                  )}
                </div>
              </div>
              <div className="card">
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 4 }}>HARDWARE</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{preset ?? "none selected"}</div>
              </div>
              <div className="card">
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 4 }}>ACCOUNTS</div>
                <div style={{ display: "flex", gap: 12 }}>
                  <div><span style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{adminUsername}</span> <span className="hex-badge" style={{ background: "var(--danger)", color: "var(--paper)", fontSize: 12 }}>admin</span></div>
                  <div><span style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{userUsername || "(not set)"}</span> <span className="hex-badge" style={{ background: "var(--accent)", color: "var(--paper)", fontSize: 12 }}>user</span></div>
                </div>
              </div>
              {modules.length > 0 && (
                <div className="card">
                  <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 4 }}>OPTIONAL MODULES</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {modules.map((m) => <span key={m} className="hex-badge">{m}</span>)}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--rule)", display: "flex", justifyContent: "space-between" }}>
          {step > 0 ? (
            <button className="btn" onClick={() => setStep(Math.max(0, step - 1))}>{"\u2190"} back</button>
          ) : (
            // Reserve the slot so the layout doesn't jump when back appears at step 1.
            <span style={{ display: "inline-block", minWidth: 60 }} />
          )}
          {step < steps.length - 1 ? (
            <button className="btn btn-accent" onClick={() => setStep(step + 1)} disabled={
              (step === 0 && !conductorName.trim()) ||
              // A failed gateway discovery or a manually entered model ID may
              // proceed only with an explicit unverified-availability
              // acknowledgement (#287) — never silently.
              (step === 0 && (modelCheck === "failed" || manualModel) && !fallbackAcknowledged) ||
              // Only require a hardware choice when there is one to make.
              // POC mode used to select "laptop" locally and skip this step
              // entirely, so retiring it exposed a pre-existing dead end: no
              // presets means no cards, and requiring a selection then blocks
              // first-run provisioning with no error and no retry (#129).
              (step === 1 && !preset && Object.keys(presets).length > 0) ||
              (step === 2 && (!adminPassword || !userUsername || !userPassword))
            }>
              next {"\u2192"}
            </button>
          ) : (
            <button className="btn btn-accent" onClick={() => void finish()} disabled={loading || (!preset && Object.keys(presets).length > 0)}>
              {loading ? "configuring..." : "launch the hive \uD83D\uDC1D"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
