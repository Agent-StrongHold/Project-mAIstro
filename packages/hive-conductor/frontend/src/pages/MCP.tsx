import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiDelete } from "../lib/api";
import { usePmPoc } from "../context/PocMode";
import { PM_NAV_INTEGRATIONS } from "../lib/pmBranding";
import { Hex, PageHeader, StatCard, ConfirmDialog, useToast } from "../components/shared";
const ROVO_MCP_URL = "https://mcp.atlassian.com/v1/mcp/authv2";

type Server = {
  id: string; name: string; description: string; url: string;
  status: string; tools_count: number; last_ping: string | null;
  version: string | null; capabilities: string[];
};

type Tool = {
  id: string; server_id: string; name: string; description: string;
  input_schema: Record<string, unknown>; category: string | null;
};

export default function MCP() {
  const pmPoc = usePmPoc();
  const toast = useToast();
  const [servers, setServers] = useState<Server[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [sel, setSel] = useState<Server | null>(null);
  const [tab, setTab] = useState<"servers" | "tools">("servers");
  const [adding, setAdding] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Server | null>(null);
  const [form, setForm] = useState({ name: "", description: "", url: "" });

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([apiGet<Server[]>("/v1/mcp/servers"), apiGet<Tool[]>("/v1/mcp/tools")]);
      setServers(s);
      setTools(t);
    } catch { /* */ }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function addServer() {
    if (!form.name.trim() || !form.url.trim()) return;
    try {
      await apiPost<Server>("/v1/mcp/servers", form);
      setAdding(false);
      setForm({ name: "", description: "", url: "" });
      await load();
      toast("Server added", "ok");
    } catch { toast("Failed to add server", "error"); }
  }

  async function testConnections() {
    try {
      const res = await apiPost<{ results?: { server_id: string; ok: boolean; detail?: string }[] }>(
        "/v1/mcp/test",
        {},
      );
      const results = res.results ?? [];
      const ok = results.filter((r) => r.ok).length;
      toast(
        results.length ? `MCP test: ${ok}/${results.length} connected` : "MCP test complete",
        ok === results.length && results.length > 0 ? "ok" : "error",
      );
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "MCP test failed", "error");
    }
  }

  async function removeServer(id: string) {
    try {
      await apiDelete(`/v1/mcp/servers/${id}`);
      if (sel?.id === id) setSel(null);
      await load();
      toast("Server removed", "ok");
    } catch { toast("Failed to remove server", "error"); }
    setDeleteTarget(null);
  }

  return (
    <div>
      <ConfirmDialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} onConfirm={() => { if (deleteTarget) void removeServer(deleteTarget.id); }} title="Remove Server" message={`Remove "${deleteTarget?.name ?? ""}" from MCP?`} />

      <PageHeader
        title={pmPoc ? PM_NAV_INTEGRATIONS : "MCP"}
        subtitle={
          pmPoc
            ? `${servers.length} MCP servers · ${tools.length} tools — container runtime, not Cursor`
            : `${servers.length} servers · ${tools.length} tools — multi-MCP orchestration in this sandbox`
        }
        helpHref={pmPoc ? undefined : "/docs#mcp"}
        actions={
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => void testConnections()}>
              Test connection
            </button>
            {!pmPoc && (
              <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => setAdding(true)}>
                + add server
              </button>
            )}
          </div>
        }
      />

      <div className="card" style={{ marginBottom: 14, padding: 14, borderLeft: "4px solid var(--accent)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 8 }}>
          FORCE CONVERGENCE · MULTI-MCP
        </div>
        <p style={{ fontFamily: "var(--hand)", fontSize: 13, margin: "0 0 10px", lineHeight: 1.45 }}>
          Hive runs inside your <strong>leased sandbox container</strong> (parent-project). Agents call MCP tools
          from this catalog using secrets in <a href="/credentials" style={{ color: "var(--accent)" }}>Credentials</a> or
          Launch env vars — <strong>not</strong> via Cursor. Canonical manifests live in MAISTRO{" "}
          <code style={{ fontFamily: "var(--mono)", fontSize: 10 }}>container_registry/MCP_servers/</code>.
        </p>
        {pmPoc && (
          <p style={{ fontFamily: "var(--hand)", fontSize: 12, margin: "0 0 10px", lineHeight: 1.4, color: "var(--pencil)" }}>
            PM demo: Jira <em>creates</em> use <strong>Jira drafts</strong> (suggest → confirm). Autonomous tasks may read/sync via MCP when configured.
          </p>
        )}
        <p style={{ fontFamily: "var(--hand)", fontSize: 11, margin: "0 0 8px", color: "var(--pencil)" }}>
          Atlassian Rovo endpoint: {ROVO_MCP_URL}. Local dev engineers may optionally use{" "}
          <code style={{ fontFamily: "var(--mono)", fontSize: 10 }}>.cursor/mcp.json</code> — that path does not run in production sandboxes.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <a
            className="btn btn-accent"
            style={{ fontSize: 9, padding: "4px 10px", textDecoration: "none" }}
            href="https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/"
            target="_blank"
            rel="noreferrer"
          >
            Rovo MCP docs
          </a>
          <a className="btn" style={{ fontSize: 9, padding: "4px 10px", textDecoration: "none" }} href="/credentials">
            Configure credentials
          </a>
        </div>
      </div>
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--rule)", marginBottom: 12 }}>
        {(["servers", "tools"] as const).map((t) => (
          <div key={t} onClick={() => setTab(t)} style={{ padding: "7px 16px", fontFamily: "var(--mono)", fontSize: 10, cursor: "pointer", borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent", color: tab === t ? "var(--ink)" : "var(--pencil)", textTransform: "capitalize" }}>{t}</div>
        ))}
      </div>

      {adding && (
        <div className="card" style={{ borderLeft: "3px solid var(--accent)", marginBottom: 10 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input className="input-field" placeholder="server name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} autoFocus />
            <input className="input-field" placeholder="description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            <input className="input-field" placeholder="URL (e.g. http://localhost:9999/mcp)" value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} />
            <div style={{ display: "flex", gap: 4 }}>
              <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => void addServer()} disabled={!form.name.trim() || !form.url.trim()}>add</button>
              <button className="btn" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => setAdding(false)}>cancel</button>
            </div>
          </div>
        </div>
      )}

      {tab === "servers" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {servers.map((s) => {
            const serverTools = tools.filter((t) => t.server_id === s.id);
            return (
              <div key={s.id} className="card" onClick={() => setSel(sel?.id === s.id ? null : s)} style={{ cursor: "pointer" }}>
                <div style={{ display: "grid", gridTemplateColumns: "12px 1fr auto auto auto", gap: 10, alignItems: "center" }}>
                  <div style={{ width: 10, height: 10, borderRadius: "50%", background: s.status === "connected" ? "var(--ok)" : "var(--danger)" }} />
                  <div>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)" }}>{s.description}</div>
                  </div>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textAlign: "center" }}>{s.tools_count} tools</span>
                  <Hex variant={s.status === "connected" ? "ok" : "danger"}>{s.status}</Hex>
                  <button className="btn" style={{ fontSize: 8, padding: "1px 6px", borderColor: "var(--danger)", color: "var(--danger)", opacity: 0.5 }} onClick={(e) => { e.stopPropagation(); setDeleteTarget(s); }}>remove</button>
                </div>

                {sel?.id === s.id && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dotted var(--rule)" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 6, marginBottom: 10 }}>
                      <StatCard label="URL" value={s.url.replace("http://", "").replace("/mcp", "")} />
                      <StatCard label="Version" value={s.version ?? "—"} />
                      <StatCard label="Last Ping" value={s.last_ping ? new Date(s.last_ping).toLocaleTimeString() : "never"} />
                      <StatCard label="Tools" value={`${s.tools_count}`} />
                    </div>
                    {s.capabilities.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 3 }}>CAPABILITIES</div>
                        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                          {s.capabilities.map((c) => <Hex key={c}>{c}</Hex>)}
                        </div>
                      </div>
                    )}
                    {serverTools.length > 0 && (
                      <div>
                        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 3 }}>TOOLS</div>
                        {serverTools.map((t) => (
                          <div key={t.id} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 6, padding: "4px 6px", borderBottom: "1px dotted var(--rule)" }}>
                            <div>
                              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--accent)" }}>{t.name}</span>
                              <span style={{ fontFamily: "var(--hand)", fontSize: 10, color: "var(--pencil)", marginLeft: 8 }}>{t.description}</span>
                            </div>
                            {t.category && <Hex variant="muted">{t.category}</Hex>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {servers.length === 0 && !adding && <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>no MCP servers configured</div>}
        </div>
      )}

      {tab === "tools" && (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead><tr><th>Tool</th><th>Server</th><th>Category</th><th>Description</th></tr></thead>
            <tbody>
              {tools.map((t) => (
                <tr key={t.id}>
                  <td style={{ color: "var(--accent)" }}>{t.name}</td>
                  <td style={{ color: "var(--pencil)" }}>{servers.find((s) => s.id === t.server_id)?.name ?? t.server_id}</td>
                  <td>{t.category ? <Hex variant="muted">{t.category}</Hex> : "—"}</td>
                  <td style={{ color: "var(--pencil)", fontSize: 8 }}>{t.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
