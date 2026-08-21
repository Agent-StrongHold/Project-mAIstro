import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import {
  Card,
  EmptyState,
  LoadingSpinner,
  PageHeader,
  StatCard,
  Tabs,
  useToast,
} from "../components/shared";

type ProviderQuota = {
  provider: string;
  status: string;
  billing_cycle: string;
  cycle_key: string;
  used_tokens: number;
  free_tokens: number;
  remaining_tokens: number;
  limit: number | null;
  usage_pct: number;
  request_count: number;
  unit: string;
};

type ModelStat = {
  model: string;
  provider: string;
  tier: string;
  quality: number;
  speed: number;
  usage_pct: number;
  available: boolean;
  context: number | null;
  modality: string | null;
  strengths: string[];
};

type OutcomeStats = {
  total: number;
  succeeded: number;
  failed: number;
  rate: number;
  by_model: Record<string, { total: number; succeeded: number; rate: number }>;
  days: number;
};

type SortKey = "model" | "provider" | "tier" | "quality" | "speed" | "usage_pct";
type SortDir = "asc" | "desc";

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(Math.round(n));
}

function usageColor(pct: number): string {
  if (pct > 80) return "#c4452a";
  if (pct > 50) return "#b8860b";
  return "#5a9a4a";
}

const tierColor: Record<string, string> = {
  frontier: "#7a5af5",
  large: "var(--accent)",
  medium: "#5b8fb3",
  small: "var(--pencil)",
};

function SortableHeader({ label, field, sortKey, sortDir, onSort }: {
  label: string; field: SortKey; sortKey: SortKey; sortDir: SortDir; onSort: (k: SortKey) => void;
}) {
  const arrow = sortKey === field ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : "";
  return (
    <th style={{ textAlign: "left", padding: "8px 10px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap", cursor: "pointer", userSelect: "none", borderBottom: "1.3px solid var(--rule)" }} onClick={() => onSort(field)}>
      {label}{arrow}
    </th>
  );
}

export default function Quotas() {
  const toast = useToast();
  const [tab, setTab] = useState(0);
  const [providers, setProviders] = useState<ProviderQuota[]>([]);
  const [models, setModels] = useState<ModelStat[]>([]);
  const [outcomes, setOutcomes] = useState<OutcomeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("quality");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [modelFilter, setModelFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [p, m, o] = await Promise.all([
          apiGet<ProviderQuota[]>("/v1/quotas/providers"),
          apiGet<ModelStat[]>("/v1/quotas/models"),
          apiGet<OutcomeStats>("/v1/quotas/outcomes"),
        ]);
        setProviders(p);
        setModels(m);
        setOutcomes(o);
      } catch {
        toast("Failed to load quota data", "error");
      }
      setLoading(false);
    })();
  }, [toast]);

  const handleSort = useCallback((key: SortKey) => {
    if (sortKey === key) setSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  }, [sortKey]);

  const providerNames = [...new Set(models.map((m) => m.provider))].sort();

  const filtered = models.filter((m) => {
    if (providerFilter !== "all" && m.provider !== providerFilter) return false;
    if (modelFilter && !m.model.toLowerCase().includes(modelFilter.toLowerCase())) return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "string" && typeof bv === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === "asc" ? Number(av) - Number(bv) : Number(bv) - Number(av);
  });

  const modelEntries = outcomes?.by_model ? Object.entries(outcomes.by_model).sort((a, b) => b[1].total - a[1].total) : [];
  const maxModelTasks = modelEntries.length > 0 ? modelEntries[0][1].total : 1;

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader title="Quotas & Stats" subtitle={`${providers.length} providers · ${models.length} models — track AI usage and costs`} helpHref="/docs#quotas" />
      <Tabs tabs={[`Providers (${providers.length})`, `Models (${models.length})`, `Outcomes (${outcomes?.total ?? 0})`]} active={tab} onChange={setTab} />

      {loading ? <LoadingSpinner /> : (
        <>
          {tab === 0 && (
            providers.length === 0 ? <EmptyState icon="📊" title="No provider data — conductor-router unreachable" /> : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
                {providers.map((p) => {
                  const tracked = p.limit !== null;
                  const pct = tracked ? p.usage_pct : 0;
                  const color = tracked ? usageColor(pct) : "var(--accent)";
                  return (
                    <Card key={p.provider}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <span style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 700 }}>{p.provider}</span>
                        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: p.status === "active" ? "#5a9a4a" : "#c4452a" }} />
                          <span style={{ fontFamily: "var(--mono)", fontSize: 8, padding: "2px 6px", borderRadius: 3, background: "rgba(91,143,179,0.12)", color: "#3a6a9a" }}>{p.cycle_key}</span>
                        </div>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2, fontFamily: "var(--mono)", fontSize: 9 }}>
                        <span style={{ fontWeight: 600, color: "var(--ink)" }}>{fmt(p.used_tokens)} {p.unit}</span>
                        <span style={{ color: tracked ? usageColor(pct) : "var(--pencil)" }}>{tracked ? `${fmt(p.limit!)} limit` : "unlimited"}</span>
                      </div>
                      <div style={{ height: 6, borderRadius: 3, background: "var(--rule)", overflow: "hidden" }}>
                        <div style={{ height: "100%", borderRadius: 3, background: color, width: `${Math.min(pct || (tracked ? 0 : 5), 100)}%`, transition: "width 0.3s" }} />
                      </div>
                      {tracked && <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: usageColor(pct), marginTop: 2 }}>{pct.toFixed(1)}% used · {fmt(p.remaining_tokens)} remaining</div>}
                      <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 4 }}>
                        {p.billing_cycle} · {p.request_count} requests
                      </div>
                    </Card>
                  );
                })}
              </div>
            )
          )}

          {tab === 1 && (
            models.length === 0 ? <EmptyState icon="🧠" title="No model data — conductor-router unreachable" /> : (
              <div>
                <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
                  <input className="input-field" style={{ width: 200 }} placeholder="Filter models..." value={modelFilter} onChange={(e) => setModelFilter(e.target.value)} />
                  <select className="input-field" style={{ width: 140 }} value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
                    <option value="all">All providers</option>
                    {providerNames.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>{sorted.length} of {models.length}</span>
                </div>
                <Card>
                  <div style={{ overflow: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 10 }}>
                      <thead>
                        <tr>
                          <SortableHeader label="Model" field="model" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Provider" field="provider" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Tier" field="tier" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Quality" field="quality" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Speed" field="speed" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <th style={{ textAlign: "left", padding: "8px 10px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", borderBottom: "1.3px solid var(--rule)" }}>Modality</th>
                          <th style={{ textAlign: "left", padding: "8px 10px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", borderBottom: "1.3px solid var(--rule)" }}>Strengths</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sorted.map((m) => (
                          <tr key={m.model} style={{ borderBottom: "1px solid var(--rule)", opacity: m.available ? 1 : 0.5 }}>
                            <td style={{ padding: "6px 10px", fontWeight: 600, whiteSpace: "nowrap" }}>{m.model}</td>
                            <td style={{ padding: "6px 10px", color: "var(--pencil)" }}>{m.provider}</td>
                            <td style={{ padding: "6px 10px" }}>
                              <span style={{ fontFamily: "var(--mono)", fontSize: 8, padding: "2px 6px", borderRadius: 3, border: `1px solid ${tierColor[m.tier] || "var(--rule)"}`, color: tierColor[m.tier] || "var(--pencil)" }}>{m.tier}</span>
                            </td>
                            <td style={{ padding: "6px 10px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <div style={{ width: 50, height: 5, borderRadius: 3, background: "var(--rule)", overflow: "hidden" }}>
                                  <div style={{ height: "100%", borderRadius: 3, background: "var(--accent)", width: `${m.quality * 100}%` }} />
                                </div>
                                <span style={{ fontSize: 9 }}>{(m.quality * 100).toFixed(0)}%</span>
                              </div>
                            </td>
                            <td style={{ padding: "6px 10px", color: "var(--pencil)" }}>{m.speed > 0 ? `${m.speed} t/s` : "-"}</td>
                            <td style={{ padding: "6px 10px", color: "var(--pencil)", fontSize: 9 }}>{m.modality || "-"}</td>
                            <td style={{ padding: "6px 10px" }}>
                              <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                                {(m.strengths || []).slice(0, 4).map((s) => (
                                  <span key={s} style={{ fontFamily: "var(--mono)", fontSize: 7.5, padding: "1px 4px", borderRadius: 2, background: "rgba(212,160,23,0.10)", border: "1px solid var(--rule)", color: "var(--pencil)" }}>{s}</span>
                                ))}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            )
          )}

          {tab === 2 && (
            !outcomes ? <EmptyState icon="🎯" title="No outcome data" /> : (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 16 }}>
                  <StatCard label="Total Requests" value={outcomes.total} highlight />
                  <StatCard label="Succeeded" value={outcomes.succeeded} />
                  <StatCard label="Failed" value={outcomes.failed} />
                  <StatCard label="Success Rate" value={`${(outcomes.rate * 100).toFixed(1)}%`} />
                </div>
                <Card>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 10, fontWeight: 600, marginBottom: 10, color: "var(--pencil)", textTransform: "uppercase" }}>
                    Per-Model Breakdown (last {outcomes.days} days)
                  </div>
                  {modelEntries.length === 0 ? (
                    <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)", textAlign: "center", padding: 20 }}>No recent activity</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {modelEntries.map(([model, info]) => {
                        const pct = (info.total / maxModelTasks) * 100;
                        return (
                          <div key={model} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ fontFamily: "var(--mono)", fontSize: 10, width: 220, textAlign: "right", color: "var(--ink)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{model}</span>
                            <div style={{ flex: 1, height: 16, borderRadius: 3, background: "var(--rule)", overflow: "hidden" }}>
                              <div style={{ height: "100%", borderRadius: 3, background: info.rate >= 1.0 ? "var(--accent)" : "#c4452a", width: `${pct}%`, transition: "width 0.3s", display: "flex", alignItems: "center", paddingLeft: 6, fontFamily: "var(--mono)", fontSize: 8, color: "var(--paper)", fontWeight: 600 }}>
                                {pct > 12 ? `${info.succeeded}/${info.total}` : ""}
                              </div>
                            </div>
                            <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", width: 60 }}>{(info.rate * 100).toFixed(0)}% ok</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </Card>
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}
