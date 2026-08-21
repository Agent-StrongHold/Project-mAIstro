import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiDelete } from "../lib/api";
import { Hex, PageHeader, StatCard } from "../components/shared";

type Container = {
  id: string; name: string; image: string; status: string;
  ports: { host?: number; container: number }[];
  cpu_usage: number; memory_usage_mb: number; memory_limit_mb: number;
  network_rx_mb: number; network_tx_mb: number;
  created_at: string; started_at: string | null;
  labels: Record<string, string>;
};

type LogData = { id: string; logs: string };

export default function Containers() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [loading, setLoading] = useState(true);
  const [logsFor, setLogsFor] = useState<{ id: string; name: string } | null>(null);
  const [logs, setLogs] = useState<string>("");
  const [logsLoading, setLogsLoading] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [showStopped, setShowStopped] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setContainers(await apiGet<Container[]>("/v1/containers"));
    } catch { /* */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function containerAction(id: string, action: "start" | "stop" | "restart") {
    setActing(id);
    try {
      await apiPost(`/v1/containers/${id}/${action}`);
      await load();
    } catch { /* */ } finally { setActing(null); }
  }

  async function removeContainer(id: string) {
    setActing(id);
    try {
      await apiDelete(`/v1/containers/${id}`);
      await load();
    } catch { /* */ } finally { setActing(null); }
  }

  async function fetchLogs(id: string, name: string) {
    setLogsFor({ id, name });
    setLogsLoading(true);
    setLogs("");
    try {
      const data = await apiGet<LogData>(`/v1/containers/${id}/logs?tail=200`);
      setLogs(data.logs || "(empty)");
    } catch {
      setLogs("(failed to fetch logs)");
    } finally { setLogsLoading(false); }
  }

  const filtered = containers.filter((c) => {
    if (!showStopped && c.status !== "running") return false;
    if (filter) {
      const q = filter.toLowerCase();
      return c.name.toLowerCase().includes(q) || c.image.toLowerCase().includes(q) || Object.values(c.labels).some((v) => v.toLowerCase().includes(q));
    }
    return true;
  });

  const running = containers.filter((c) => c.status === "running").length;

  return (
    <div style={{ display: logsFor ? "grid" : "block", gridTemplateColumns: logsFor ? "1fr 420px" : "1fr", gap: 0, minHeight: "calc(100vh - 60px)" }}>
      <div>
        <PageHeader
          title="Containers"
          subtitle={`${running} running · ${containers.length} total — Docker services powering your system`}
          helpHref="/docs#containers"
          actions={<button className="btn" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => void load()}>refresh</button>}
        />
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <input className="input-field" placeholder="filter by name, image, label..." value={filter} onChange={(e) => setFilter(e.target.value)} style={{ flex: 1, maxWidth: 320 }} />
            <label style={{ display: "flex", gap: 4, alignItems: "center", fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", cursor: "pointer" }}>
              <input type="checkbox" checked={showStopped} onChange={(e) => setShowStopped(e.target.checked)} />
              show stopped
            </label>
          </div>

        {loading && containers.length === 0 ? (
          <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>loading containers...</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {filtered.map((c) => {
              const memPct = c.memory_limit_mb > 0 ? (c.memory_usage_mb / c.memory_limit_mb) * 100 : 0;
              const isActing = acting === c.id;
              const isRunning = c.status === "running";

              return (
                <div key={c.id} className="card" style={{ opacity: isActing ? 0.6 : 1 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center" }}>
                    <div>
                      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                        <span style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600 }}>{c.name}</span>
                        <Hex variant={isRunning ? "ok" : c.status === "restarting" ? "warn" : "muted"}>{c.status}</Hex>
                      </div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 2 }}>{c.image}</div>
                    </div>
                    <div style={{ display: "flex", gap: 3 }}>
                      {isRunning ? (
                        <>
                          <button className="btn" style={{ fontSize: 8, padding: "1px 6px" }} onClick={() => void containerAction(c.id, "restart")} disabled={isActing}>restart</button>
                          <button className="btn" style={{ fontSize: 8, padding: "1px 6px", borderColor: "var(--warn)", color: "var(--warn)" }} onClick={() => void containerAction(c.id, "stop")} disabled={isActing}>stop</button>
                          <button className="btn" style={{ fontSize: 8, padding: "1px 6px" }} onClick={() => void fetchLogs(c.id, c.name)}>logs</button>
                        </>
                      ) : (
                        <>
                          <button className="btn" style={{ fontSize: 8, padding: "1px 6px", borderColor: "var(--ok)", color: "var(--ok)" }} onClick={() => void containerAction(c.id, "start")} disabled={isActing}>start</button>
                          <button className="btn" style={{ fontSize: 8, padding: "1px 6px", borderColor: "var(--danger)", color: "var(--danger)", opacity: 0.6 }} onClick={() => void removeContainer(c.id)} disabled={isActing}>remove</button>
                        </>
                      )}
                    </div>
                  </div>

                  {c.ports.length > 0 && (
                    <div style={{ display: "flex", gap: 4, marginTop: 6, flexWrap: "wrap" }}>
                      {c.ports.map((p, i) => (
                        <Hex key={i} variant="accent">{p.host != null ? `${p.host}:${p.container}` : `:${p.container}`}</Hex>
                      ))}
                    </div>
                  )}

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))", gap: 6, marginTop: 8 }}>
                    <StatCard label="CPU" value={`${c.cpu_usage.toFixed(1)}%`} highlight={c.cpu_usage > 50} />
                    <StatCard label="Memory" value={`${Math.round(c.memory_usage_mb)}/${Math.round(c.memory_limit_mb)}MB`} />
                    <StatCard label="Net I/O" value={`${c.network_rx_mb.toFixed(1)}/${c.network_tx_mb.toFixed(1)}MB`} />
                  </div>

                  {isRunning && c.memory_limit_mb > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginBottom: 2 }}>MEMORY {memPct.toFixed(0)}%</div>
                      <div className="progress-bar">
                        <div className="progress-bar-fill" style={{ width: `${Math.min(memPct, 100)}%`, background: memPct > 80 ? "var(--danger)" : memPct > 50 ? "var(--warn)" : "var(--ok)" }} />
                      </div>
                    </div>
                  )}

                  {Object.keys(c.labels).length > 0 && (
                    <div style={{ display: "flex", gap: 4, marginTop: 6, flexWrap: "wrap" }}>
                      {Object.entries(c.labels).filter(([k]) => k.startsWith("com.docker.compose") || k === "traefik.enable").slice(0, 4).map(([k, v]) => (
                        <Hex key={k} variant="muted">{k.split(".").pop()}: {v.length > 20 ? v.slice(0, 20) + "..." : v}</Hex>
                      ))}
                    </div>
                  )}

                  <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 6 }}>
                    created: {new Date(c.created_at).toLocaleString()} · id: {c.id}
                  </div>
                </div>
              );
            })}
            {filtered.length === 0 && !loading && (
              <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>
                {containers.length === 0 ? "no containers found (Docker socket may not be mounted)" : "no containers match filter"}
              </div>
            )}
          </div>
        )}
      </div>

      {logsFor && (
        <div style={{ borderLeft: "1.5px dashed var(--honey)", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "8px 0 6px 10px" }}>
            <div>
              <span style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600 }}>{logsFor.name}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginLeft: 8 }}>logs</span>
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              <button className="btn" style={{ fontSize: 8, padding: "1px 6px" }} onClick={() => void fetchLogs(logsFor.id, logsFor.name)}>refresh</button>
              <span className="btn" style={{ fontSize: 8, padding: "1px 6px" }} onClick={() => { setLogsFor(null); setLogs(""); }}>close</span>
            </div>
          </div>
          <div style={{ flex: 1, margin: "0 0 0 10px", background: "var(--ink)", color: "var(--paper)", fontFamily: "var(--mono)", fontSize: 9, padding: "10px 12px", borderRadius: 4, overflow: "auto", maxHeight: "calc(100vh - 140px)", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.6 }}>
            {logsLoading ? "loading..." : logs}
          </div>
        </div>
      )}
    </div>
  );
}
