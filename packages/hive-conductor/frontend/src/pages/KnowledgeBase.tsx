import { useCallback, useEffect, useState, type KeyboardEvent } from "react";

interface MemoryEntry { id: string; key: string; value: string; namespace: string; tags: string[]; }
interface Namespace { name: string; count: number; }

const C = { bg: "#0a0914", card: "#11101e", border: "rgba(196,166,97,0.14)", gold: "#c4a661", ink: "#f3f0fb", muted: "#8b83a8", dim: "#5a5478", acc: "#a78bfa", ok: "#7cd4a0", danger: "#e87c7c" };

const PROFILE_SECTIONS = {
  identity: { label: "Identity", fields: ["name", "role", "team", "department", "location", "timezone"] },
  work: { label: "Work Context", fields: ["projects", "tools", "languages", "platforms", "recurring_tasks", "stakeholders"] },
  preferences: { label: "Preferences", fields: ["response_style", "interaction_style", "model_preferences", "topics_to_avoid", "assumptions_to_avoid"] },
  goals: { label: "Goals & Focus", fields: ["current_focus", "okrs", "blockers", "definition_of_done"] },
  communication: { label: "Communication", fields: ["challenge_style", "presentation_format", "terminology"] },
};

const PROMPT_SECTIONS = [
  { id: "chat", label: "Chat Assistant", desc: "Main chat page behavior" },
  { id: "widget_wizard", label: "Widget Wizard", desc: "Dashboard edit mode" },
  { id: "biographer", label: "Biographer", desc: "Compendium profile builder" },
];

type Tab = "prompts" | "profile" | "memories" | "settings";

export default function KnowledgeBase() {
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [namespaces, setNamespaces] = useState<Namespace[]>([]);
  const [activeNs, setActiveNs] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [newContent, setNewContent] = useState("");
  const [newTags, setNewTags] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatHistory, setChatHistory] = useState<{role: string; content: string}[]>([]);
  const [profile, setProfile] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<Tab>("profile");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [prompts, setPrompts] = useState<Record<string, { system: string; user: string }>>({
    chat: { system: "", user: "" },
    widget_wizard: { system: "", user: "" },
    biographer: { system: "", user: "" },
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ns, ents] = await Promise.all([
        fetch("/v1/memory/namespaces", { credentials: "same-origin" }).then(r => r.json()),
        fetch(`/v1/memory/entries${activeNs ? `?namespace=${activeNs}` : ""}`, { credentials: "same-origin" }).then(r => r.json()),
      ]);
      setNamespaces(ns); setEntries(ents);
    } catch { /* */ }
    try {
      const p = await fetch("/v1/profile", { credentials: "same-origin" }).then(r => r.json());
      setProfile(p?.preferences || {});
      if (p?.preferences?.prompts) setPrompts(p.preferences.prompts);
    } catch { /* */ }
    try {
      const s = await fetch("/v1/settings", { credentials: "same-origin" }).then(r => r.json());
      setSettings(s || {});
    } catch { /* */ }
    setLoading(false);
  }, [activeNs]);

  useEffect(() => { load(); }, [load]);

  const savePrompt = async (section: string, field: "user", value: string) => {
    const updated = { ...prompts, [section]: { ...prompts[section], [field]: value } };
    setPrompts(updated);
    await fetch("/v1/profile", { method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preferences: { ...profile, prompts: updated } }) }).catch(() => {});
  };

  const addEntry = async () => {
    if (!newContent.trim()) return;
    await fetch("/v1/memory/entries", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: newContent.trim().slice(0, 60), value: newContent.trim(), namespace: activeNs || "general", tags: newTags.split(",").map(t => t.trim()).filter(Boolean) }) });
    setNewContent(""); setNewTags(""); load();
  };

  const deleteEntry = async (id: string) => { await fetch(`/v1/memory/entries/${id}`, { method: "DELETE", credentials: "same-origin" }); load(); };
  const reinforceEntry = async (id: string) => { await fetch(`/v1/memory/entries/${id}/reinforce`, { method: "POST", credentials: "same-origin" }); load(); };

  const MEMORY_SYSTEM = `You are Blake's memory assistant. Your job is to learn about the user and fill their profile through natural conversation. Be warm but brief — one sentence acknowledgment, then keep the conversation moving.

On EVERY message:
1. If they share info — call profile_set or memory_add immediately, acknowledge casually, then ask the next thing.
2. If they're vague — call profile_get to check gaps, then ask about the most interesting unfilled field conversationally.
3. If they ask to change settings (model, response style, etc.) — use profile_set with the right field.
4. Always end with a follow-up. Keep momentum.

Tools: profile_set, profile_get, profile_delete, memory_add, memory_search, memory_delete.
Profile fields: name, role, team, department, location, timezone, projects, tools, languages, platforms, recurring_tasks, stakeholders, response_style, interaction_style, model_preferences, topics_to_avoid, assumptions_to_avoid, current_focus, okrs, blockers, definition_of_done, challenge_style, presentation_format, terminology.

Current memories:\n${entries.slice(0, 15).map(e => `- [${e.namespace}] ${e.value}`).join("\n") || "(none yet)"}`;

  const chatAsk = async () => {
    if (!chatInput.trim() || chatLoading) return;
    setChatLoading(true); setChatInput("");
    const newHistory = [...chatHistory, { role: "user", content: chatInput.trim() }];
    setChatHistory(newHistory);
    try {
      const res = await fetch("/v1/chat/stream", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tools_scope: "memory", messages: [{ role: "system", content: MEMORY_SYSTEM }, ...newHistory.slice(-10)] }) });
      if (!res.ok) throw new Error(`${res.status}`);
      const reader = res.body?.getReader(); const decoder = new TextDecoder(); let acc = "";
      if (reader) { while (true) { const { done, value } = await reader.read(); if (done) break;
        for (const line of decoder.decode(value, { stream: true }).split("\n")) { if (!line.startsWith("data: ")) continue;
          try { const e = JSON.parse(line.slice(6)); if (e.type === "token" || e.type === "content") acc += e.content || e.token || ""; else if (e.type === "done" && e.content && !acc) acc = e.content; } catch { /* SSE chunk split a JSON payload mid-object — wait for the rest */ } }
        setChatHistory([...newHistory, { role: "assistant", content: acc }]); } }
      setChatHistory([...newHistory, { role: "assistant", content: acc || "No response" }]); load();
    } catch { setChatHistory([...newHistory, { role: "assistant", content: "Error — try again" }]); }
    setChatLoading(false);
  };

  const filledFields = Object.keys(profile).filter(k => k !== "prompts").length;
  const totalFields = Object.values(PROFILE_SECTIONS).reduce((n, s) => n + s.fields.length, 0);

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.ink, fontFamily: "'Inter', -apple-system, system-ui, sans-serif", padding: "1.5rem 2rem" }}>
      <div style={{ marginBottom: "1rem" }}>
        <h1 style={{ fontSize: "1.3rem", fontWeight: 700, margin: 0, fontFamily: "Georgia, serif" }}>Inner Temple</h1>
        <p style={{ fontSize: "0.7rem", color: C.muted, margin: "2px 0 0" }}>Your personal chamber — identity, preferences, and everything Fantasia knows about you</p>
      </div>

      {/* Persistent Chat Bar */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: "10px 14px", marginBottom: "1rem" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: C.gold, fontSize: "0.8rem" }}>✦</span>
          <input value={chatInput} onChange={e => setChatInput(e.target.value)} onKeyDown={(e: KeyboardEvent) => e.key === "Enter" && chatAsk()}
            placeholder="Tell me about yourself, change a setting, or ask what I know..." disabled={chatLoading} autoFocus
            style={{ flex: 1, border: "none", background: "transparent", color: C.ink, fontSize: "0.82rem", outline: "none" }} />
          {chatLoading && <span style={{ fontSize: "0.65rem", color: C.muted }}>…</span>}
        </div>
        {chatHistory.length > 0 && (
          <div style={{ marginTop: 8, maxHeight: 160, overflowY: "auto", display: "flex", flexDirection: "column-reverse", gap: 5 }}>
            {[...chatHistory].reverse().map((m, i) => (
              <div key={i} style={{ padding: "5px 10px", borderRadius: 8, background: m.role === "user" ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.3)", fontSize: "0.76rem", color: C.ink, lineHeight: 1.4, whiteSpace: "pre-wrap" }}>
                <span style={{ fontSize: "0.58rem", color: C.muted, marginRight: 5 }}>{m.role === "user" ? "You" : "✦"}</span>{m.content}
              </div>
            ))}
            <button onClick={() => setChatHistory([])} style={{ alignSelf: "flex-end", background: "none", border: "none", color: C.dim, cursor: "pointer", fontSize: "0.58rem" }}>clear</button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 2, marginBottom: "1rem", borderBottom: `1px solid ${C.border}`, paddingBottom: 2 }}>
        {([["prompts", "Prompts"], ["profile", `Profile (${filledFields}/${totalFields})`], ["memories", `Memories (${entries.length})`], ["settings", "Settings"]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} onClick={() => setTab(t)} style={{ padding: "7px 14px", borderRadius: "8px 8px 0 0", border: "none", cursor: "pointer", fontSize: "0.72rem", fontWeight: 600, background: tab === t ? "rgba(167,139,250,0.12)" : "transparent", color: tab === t ? C.ink : C.muted, borderBottom: tab === t ? `2px solid ${C.acc}` : "2px solid transparent" }}>
            {label}
          </button>
        ))}
      </div>

      {/* Prompts Tab */}
      {tab === "prompts" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {PROMPT_SECTIONS.map(s => (
            <div key={s.id} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <div>
                  <div style={{ fontSize: "0.75rem", fontWeight: 600, color: C.ink }}>{s.label}</div>
                  <div style={{ fontSize: "0.6rem", color: C.muted }}>{s.desc}</div>
                </div>
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: "0.58rem", color: C.dim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>System Prompt (admin only)</div>
                <div style={{ background: "rgba(0,0,0,0.3)", borderRadius: 6, padding: "8px 10px", fontSize: "0.7rem", color: C.muted, lineHeight: 1.4, maxHeight: 80, overflowY: "auto", whiteSpace: "pre-wrap" }}>
                  {prompts[s.id]?.system || "(default — managed by system)"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: "0.58rem", color: C.gold, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Your additions (editable)</div>
                <textarea value={prompts[s.id]?.user || ""} onChange={e => { const v = e.target.value; setPrompts(p => ({ ...p, [s.id]: { ...p[s.id], user: v } })); }}
                  onBlur={e => savePrompt(s.id, "user", e.target.value)}
                  placeholder="Add instructions, context, or style guidance..."
                  style={{ width: "100%", minHeight: 60, border: `1px solid ${C.border}`, background: "rgba(0,0,0,0.2)", borderRadius: 6, padding: "8px 10px", color: C.ink, fontSize: "0.72rem", resize: "vertical", outline: "none", fontFamily: "inherit", lineHeight: 1.4 }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Profile Tab */}
      {tab === "profile" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {Object.entries(PROFILE_SECTIONS).map(([key, section]) => (
            <div key={key} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ fontSize: "0.6rem", fontWeight: 600, color: C.gold, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>{section.label}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "4px 16px" }}>
                {section.fields.map(f => (
                  <div key={f} style={{ fontSize: "0.72rem", padding: "2px 0" }}>
                    <span style={{ color: C.muted }}>{f.replace(/_/g, " ")}: </span>
                    <span style={{ color: profile[f] ? C.ink : C.dim }}>{profile[f] || "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Memories Tab */}
      {tab === "memories" && (
        <div style={{ display: "flex", gap: "1rem" }}>
          <div style={{ width: 130, flexShrink: 0 }}>
            <div style={{ fontSize: "0.58rem", fontWeight: 600, color: C.gold, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Namespaces</div>
            <button onClick={() => setActiveNs(null)} style={{ display: "block", width: "100%", textAlign: "left", padding: "4px 8px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: "0.7rem", marginBottom: 2, background: !activeNs ? "rgba(167,139,250,0.1)" : "transparent", color: !activeNs ? C.ink : C.muted }}>All ({entries.length})</button>
            {namespaces.map(ns => (
              <button key={ns.name} onClick={() => setActiveNs(ns.name)} style={{ display: "block", width: "100%", textAlign: "left", padding: "4px 8px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: "0.7rem", marginBottom: 2, background: activeNs === ns.name ? "rgba(167,139,250,0.1)" : "transparent", color: activeNs === ns.name ? C.ink : C.muted }}>{ns.name} ({ns.count})</button>
            ))}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 10, marginBottom: 10 }}>
              <textarea value={newContent} onChange={e => setNewContent(e.target.value)} placeholder="Add a memory..." rows={2}
                style={{ width: "100%", border: "none", background: "transparent", color: C.ink, fontSize: "0.76rem", resize: "vertical", outline: "none", fontFamily: "inherit" }} />
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                <input value={newTags} onChange={e => setNewTags(e.target.value)} placeholder="tags" style={{ flex: 1, border: `1px solid ${C.border}`, background: "transparent", borderRadius: 6, padding: "3px 8px", color: C.ink, fontSize: "0.66rem", outline: "none" }} />
                <button onClick={addEntry} disabled={!newContent.trim()} style={{ padding: "3px 10px", borderRadius: 6, border: "none", background: C.acc, color: "#fff", fontSize: "0.66rem", fontWeight: 600, cursor: "pointer", opacity: newContent.trim() ? 1 : 0.4 }}>Save</button>
              </div>
            </div>
            {loading ? <div style={{ color: C.muted, fontSize: "0.72rem" }}>Loading...</div> :
              entries.length === 0 ? <div style={{ color: C.muted, fontSize: "0.72rem" }}>No memories yet.</div> :
              entries.map(e => (
                <div key={e.id} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", marginBottom: 6 }}>
                  <div style={{ fontSize: "0.74rem", color: C.ink, lineHeight: 1.4 }}>{e.value}</div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
                    <div style={{ display: "flex", gap: 3 }}>
                      <span style={{ fontSize: "0.56rem", padding: "1px 5px", borderRadius: 4, background: "rgba(167,139,250,0.1)", color: C.acc }}>{e.namespace}</span>
                      {e.tags?.map(t => <span key={t} style={{ fontSize: "0.56rem", padding: "1px 5px", borderRadius: 4, background: "rgba(196,166,97,0.08)", color: C.gold }}>{t}</span>)}
                    </div>
                    <div style={{ display: "flex", gap: 3 }}>
                      <button onClick={() => reinforceEntry(e.id)} style={{ background: "none", border: "none", color: C.ok, cursor: "pointer", fontSize: "0.58rem" }}>↑</button>
                      <button onClick={() => deleteEntry(e.id)} style={{ background: "none", border: "none", color: C.danger, cursor: "pointer", fontSize: "0.58rem" }}>✕</button>
                    </div>
                  </div>
                </div>
              ))
            }
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {tab === "settings" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ fontSize: "0.6rem", fontWeight: 600, color: C.gold, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>Model Preferences</div>
            {profile.favorite_models && (
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontSize: "0.6rem", color: C.muted }}>Favorites: </span>
                <span style={{ fontSize: "0.72rem", color: C.ink }}>{(profile.favorite_models as unknown as string[] || []).join(", ") || "—"}</span>
              </div>
            )}
            {profile.task_models && (
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontSize: "0.6rem", color: C.muted }}>Per-task: </span>
                {Object.entries(profile.task_models as unknown as Record<string, string> || {}).map(([t, m]) => (
                  <span key={t} style={{ fontSize: "0.68rem", color: C.ink, marginRight: 10 }}>{t.replace(/_/g, " ")}: {m}</span>
                ))}
                {!Object.keys(profile.task_models || {}).length && <span style={{ fontSize: "0.72rem", color: C.dim }}>—</span>}
              </div>
            )}
            {profile.hidden_models && (profile.hidden_models as unknown as string[] || []).length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontSize: "0.6rem", color: C.muted }}>Hidden: </span>
                <span style={{ fontSize: "0.68rem", color: C.dim }}>{(profile.hidden_models as unknown as string[]).join(", ")}</span>
              </div>
            )}
            <p style={{ fontSize: "0.6rem", color: C.dim, margin: "8px 0 0" }}>Use chat: "favorite gpt-5.5" · "hide cerebras" · "use claude for widget wizard"</p>
          </div>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ fontSize: "0.6rem", fontWeight: 600, color: C.gold, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>System</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: "6px 20px" }}>
              {[["default_model", "Default Model"], ["fallback_model", "Fallback Model"], ["max_tokens", "Max Tokens"], ["stream_responses", "Streaming"], ["theme", "Theme"]].map(([key, label]) => (
                <div key={key} style={{ fontSize: "0.72rem", padding: "3px 0", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: C.muted }}>{label}</span>
                  <span style={{ color: C.ink }}>{String(settings[key] ?? "—")}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
