import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";

type Preset = { name: string; label: string; description: string; max_vcpu: number; max_memory_gb: number; db_backend: string; networking: string; gpu_available: boolean; reactor_enabled: boolean; max_agents: number };

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

  const steps = ["Hive", "Hardware", "Accounts", "Modules", "Confirm"];

  // Load available models from the LLM gateway via Hive's
  // /v1/settings/models proxy. The user's LITELLM key stays server-side.
  // Setup runs BEFORE any login, so the auth-gated /v1/settings/models will
  // 401; that's expected — we fall back to a curated list of known
  // LLM-gateway models so the dropdown is always populated. After the
  // admin user finishes setup, settings can refresh the list from the
  // live gateway.
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

    // Best-effort: ask the live gateway for the latest list; replace if we
    // get a non-empty response. If we're pre-login the 401 just keeps the
    // fallback. Settings page (post-login) gets a richer refresh path.
    let active = true;
    setModelsLoading(true);
    apiGet<{ models: string[] }>("/v1/settings/models")
      .then((data) => {
        if (!active) return;
        const models = (data.models ?? []).filter(Boolean);
        if (models.length > 0) {
          setAvailableModels(models);
          if (!models.includes(routerModel)) {
            const preferred =
              models.find((m) => m === "gemini-3.1-flash-lite") ??
              models.find((m) => m.startsWith("gemini-") && m.includes("flash")) ??
              models[0];
            setRouterModel(preferred);
          }
        }
      })
      .catch(() => {
        /* pre-login 401 expected — fallback list is already in place */
      })
      .finally(() => {
        if (active) setModelsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

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
        /* pre-login 401 expected — the wizard renders without presets */
      });
    return () => {
      active = false;
    };
  }, []);

  async function finish() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/v1/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conductor_name: conductorName,
          default_model: routerModel,
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
        throw new Error(data.detail ?? `${res.status}`);
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
            <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--danger)", marginTop: 4 }}>WRITE THESE DOWN. They will never be shown again. This is the root of trust for your hive.</div>
          </div>
          <div style={{ padding: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 }}>
              {mnemonic.map((word, i) => (
                <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 11, padding: "4px 6px", border: "1px solid var(--rule)", borderRadius: 3, display: "flex", gap: 4 }}>
                  <span style={{ color: "var(--pencil)", fontSize: 9 }}>{i + 1}.</span> {word}
                </div>
              ))}
            </div>
            {didKey && (
              <div style={{ marginTop: 12, padding: "6px 8px", background: "var(--honey-light)", borderRadius: 4, fontFamily: "var(--mono)", fontSize: 8, wordBreak: "break-all" }}>
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
            <div key={s} style={{ flex: 1, padding: "8px 0", textAlign: "center", fontFamily: "var(--mono)", fontSize: 9, cursor: "pointer", borderBottom: step === i ? "2px solid var(--accent)" : "2px solid transparent", color: step === i ? "var(--ink)" : i < step ? "var(--ok)" : "var(--pencil)", fontWeight: step === i ? 700 : 400 }} onClick={() => { if (i < step) setStep(i); }}>
              <div style={{ width: 18, height: 18, borderRadius: "50%", border: `1.3px solid ${i <= step ? "var(--accent)" : "var(--rule)"}`, background: i < step ? "var(--accent)" : "transparent", color: i < step ? "var(--paper)" : "var(--pencil)", margin: "0 auto 3px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8 }}>
                {i < step ? "\u2713" : i + 1}
              </div>
              {s}
            </div>
          ))}
        </div>

        <div style={{ padding: "16px 20px", minHeight: 240 }}>
          {error && <div style={{ padding: "6px 10px", background: "rgba(196,69,42,0.12)", border: "1px solid var(--danger)", borderRadius: 4, fontFamily: "var(--mono)", fontSize: 9, color: "var(--danger)", marginBottom: 10 }}>{error}</div>}

          {step === 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600 }}>
                Name your hive
              </div>
              <div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 3 }}>CONDUCTOR NAME</div>
                <input className="input-field" placeholder="Hive Conductor" value={conductorName} onChange={(e) => setConductorName(e.target.value)} />
              </div>
              <div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 3 }}>ROUTER MODEL</div>
                {availableModels.length > 0 ? (
                  <select
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
                ) : (
                  <input
                    className="input-field"
                    placeholder={modelsLoading ? "Loading models from gateway…" : "gemini-3.1-flash-lite"}
                    value={routerModel}
                    onChange={(e) => setRouterModel(e.target.value)}
                    disabled={modelsLoading}
                  />
                )}
                <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 4 }}>
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
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {Object.values(presets).map((p) => (
                  <div key={p.name} onClick={() => setPreset(p.name)} style={{ padding: 10, border: `1.4px solid ${preset === p.name ? "var(--accent)" : "var(--ink)"}`, borderRadius: 6, cursor: "pointer", background: preset === p.name ? "var(--honey-light)" : "transparent" }}>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 17, fontWeight: 600, color: preset === p.name ? "var(--accent)" : "var(--ink)" }}>{p.label}</div>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", margin: "3px 0" }}>{p.description}</div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)" }}>{p.max_vcpu} vCPU · {p.max_memory_gb}GB · {p.db_backend} · {p.max_agents} agents{p.gpu_available ? " · GPU" : ""}</div>
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
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--danger)", marginBottom: 6 }}>ADMIN (BREAK-GLASS)</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input className="input-field" placeholder="admin" value={adminUsername} onChange={(e) => setAdminUsername(e.target.value)} style={{ flex: 1 }} />
                  <input className="input-field" type="password" placeholder="password" value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} style={{ flex: 1 }} />
                </div>
              </div>
              <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--accent)", marginBottom: 6 }}>DAILY USER</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input className="input-field" placeholder="username" value={userUsername} onChange={(e) => setUserUsername(e.target.value)} style={{ flex: 1 }} />
                  <input className="input-field" type="password" placeholder="password" value={userPassword} onChange={(e) => setUserPassword(e.target.value)} style={{ flex: 1 }} />
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
                return (
                  <div key={m.id} className="card" style={{ display: "grid", gridTemplateColumns: "1fr 36px", gap: 8, alignItems: "center", opacity: depsMet || enabled ? 1 : 0.5 }}>
                    <div>
                      <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>{m.name}</div>
                      <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)" }}>{m.desc}</div>
                      {m.requires.length > 0 && <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 2 }}>requires: {m.requires.join(", ")}</div>}
                    </div>
                    <div className={`toggle${enabled ? " on" : ""}`} onClick={() => { if (depsMet || enabled) setModules(enabled ? modules.filter((x) => x !== m.id) : [...modules, m.id]); }} />
                  </div>
                );
              })}
            </div>
          )}

          {step === 4 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600 }}>Confirm configuration</div>
              <div className="card">
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 4 }}>HIVE</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{conductorName}</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 2 }}>router: {routerModel}</div>
              </div>
              <div className="card">
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 4 }}>HARDWARE</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{preset ?? "none selected"}</div>
              </div>
              <div className="card">
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 4 }}>ACCOUNTS</div>
                <div style={{ display: "flex", gap: 12 }}>
                  <div><span style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{adminUsername}</span> <span className="hex-badge" style={{ background: "var(--danger)", color: "var(--paper)", fontSize: 8 }}>admin</span></div>
                  <div><span style={{ fontFamily: "var(--hand)", fontSize: 16 }}>{userUsername || "(not set)"}</span> <span className="hex-badge" style={{ background: "var(--accent)", color: "var(--paper)", fontSize: 8 }}>user</span></div>
                </div>
              </div>
              {modules.length > 0 && (
                <div className="card">
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 4 }}>OPTIONAL MODULES</div>
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
              (step === 1 && !preset) ||
              (step === 2 && (!adminPassword || !userUsername || !userPassword))
            }>
              next {"\u2192"}
            </button>
          ) : (
            <button className="btn btn-accent" onClick={() => void finish()} disabled={loading || !preset}>
              {loading ? "configuring..." : "launch the hive \uD83D\uDC1D"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
