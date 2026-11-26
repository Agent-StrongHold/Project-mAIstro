import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import {
  Card,
  EmptyState,
  LoadingSpinner,
  PageHeader,
  Tabs,
  useToast,
} from "../components/shared";

// Every quota endpoint answers with an envelope (#380): a state that says
// whether the numbers are measured, plus provenance naming the source, the
// window, and when this was computed. Unmeasured fields are null — the panel
// renders "n/a" / "unlimited" from those, never from an invented zero.
type PanelEnvelope = {
  state: "ok" | "no_data" | "unavailable" | "error";
  source: string;
  window_days: number | null;
  computed_at: string;
  reason: string | null;
};

type ProviderQuota = {
  provider: string;
  status: string;
  billing_cycle: string;
  cycle_key: string;
  used_tokens: number;
  free_tokens: number | null;
  remaining_tokens: number | null;
  limit: number | null;
  usage_pct: number | null;
  request_count: number | null;
  unit: string;
};

type ProvidersResponse = PanelEnvelope & { providers: ProviderQuota[] };

type ModelStat = {
  model: string;
  provider: string;
  tier: string | null;
  quality: number | null;
  speed: number | null;
  usage_pct: number | null;
  available: boolean;
  context: number | null;
  modality: string | null;
  strengths: string[];
};

type ModelsResponse = PanelEnvelope & { models: ModelStat[] };

type OutcomesResponse = PanelEnvelope;

type SortKey = "model" | "provider" | "tier" | "quality" | "speed" | "usage_pct";
type SortDir = "asc" | "desc";

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "n/a";
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
    <th style={{ textAlign: "left", padding: "8px 10px", color: "var(--pencil)", fontWeight: 600, fontSize: 12, textTransform: "uppercase", whiteSpace: "nowrap", cursor: "pointer", userSelect: "none", borderBottom: "1.3px solid var(--rule)" }} onClick={() => onSort(field)}>
      {label}{arrow}
    </th>
  );
}

/** The provenance line every panel footer shows (#380): source, window, freshness. */
function ProvenanceFooter({ panel }: { panel: PanelEnvelope }) {
  return (
    <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)", marginTop: 10, textAlign: "center", opacity: 0.85 }} title={`${panel.source} · computed ${panel.computed_at}${panel.reason ? ` · ${panel.reason}` : ""}`}>
      {panel.source}
      {panel.window_days !== null && panel.window_days !== undefined ? ` · last ${panel.window_days} days` : ""}
      {` · as of ${new Date(panel.computed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}
    </div>
  );
}

/** ok/no_data/unavailable/error are different pages, not the same empty grid. */
function PanelState({ panel, emptyTitle }: { panel: PanelEnvelope; emptyTitle: string }) {
  if (panel.state === "error") {
    return <EmptyState icon="⚠" title={`Source error — ${panel.reason || "the upstream source failed"}`} />;
  }
  if (panel.state === "unavailable") {
    return <EmptyState icon="🚫" title={`Unavailable — ${panel.reason || "no source measures this"}`} />;
  }
  return <EmptyState icon="📊" title={emptyTitle} />;
}

export default function Quotas() {
  const toast = useToast();
  const [tab, setTab] = useState(0);
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [outcomes, setOutcomes] = useState<OutcomesResponse | null>(null);
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
          apiGet<ProvidersResponse>("/v1/quotas/providers"),
          apiGet<ModelsResponse>("/v1/quotas/models"),
          apiGet<OutcomesResponse>("/v1/quotas/outcomes"),
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

  const modelList: ModelStat[] = models?.models ?? [];
  const providerList: ProviderQuota[] = providers?.providers ?? [];
  const providerNames = [...new Set(modelList.map((m) => m.provider))].sort();

  const filtered = modelList.filter((m) => {
    if (providerFilter !== "all" && m.provider !== providerFilter) return false;
    if (modelFilter && !m.model.toLowerCase().includes(modelFilter.toLowerCase())) return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === "string" && typeof bv === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === "asc" ? Number(av) - Number(bv) : Number(bv) - Number(av);
  });

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader title="Quotas & Stats" subtitle={`${providerList.length} providers · ${modelList.length} models — track AI usage and costs`} helpHref="/docs#quotas" />
      <Tabs tabs={[`Providers (${providerList.length})`, `Models (${modelList.length})`, "Outcomes (unmeasured)"]} active={tab} onChange={setTab} />

      {loading ? <LoadingSpinner /> : (
        <>
          {tab === 0 && (
            !providers || providers.state !== "ok" ? <PanelState panel={providers ?? { state: "unavailable", source: "unknown", window_days: null, computed_at: "", reason: "quota data did not load" }} emptyTitle="No provider data" /> : (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
                  {providerList.map((p) => {
                    const tracked = p.limit !== null && p.usage_pct !== null;
                    const pct = tracked ? (p.usage_pct as number) : 0;
                    const color = tracked ? usageColor(pct) : "var(--accent)";
                    return (
                      <Card key={p.provider}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                          <span style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 700 }}>{p.provider}</span>
                          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: p.status === "active" ? "#5a9a4a" : "#c4452a" }} />
                            <span style={{ fontFamily: "var(--mono)", fontSize: 12, padding: "2px 6px", borderRadius: 3, background: "rgba(91,143,179,0.12)", color: "#3a6a9a" }}>{p.cycle_key}</span>
                          </div>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2, fontFamily: "var(--mono)", fontSize: 12 }}>
                          <span style={{ fontWeight: 600, color: "var(--ink)" }}>{fmt(p.used_tokens)} {p.unit}</span>
                          <span style={{ color: tracked ? usageColor(pct) : "var(--pencil)" }}>{tracked ? `${fmt(p.limit)} limit` : "no quota limit exposed"}</span>
                        </div>
                        <div style={{ height: 6, borderRadius: 3, background: "var(--rule)", overflow: "hidden" }} title={tracked ? `${pct.toFixed(1)}% used` : "the gateway exposes no quota limit, so there is nothing to fill this bar"} >
                          <div style={{ height: "100%", borderRadius: 3, background: tracked ? color : "var(--rule)", width: tracked ? `${Math.min(pct, 100)}%` : "0%", transition: "width 0.3s" }} />
                        </div>
                        {tracked && <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: usageColor(pct), marginTop: 2 }}>{pct.toFixed(1)}% used · {fmt(p.remaining_tokens)} remaining</div>}
                        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginTop: 4 }}>
                          {p.billing_cycle} · {p.request_count === null ? "request count not reported" : `${p.request_count} requests`}
                        </div>
                      </Card>
                    );
                  })}
                </div>
                <ProvenanceFooter panel={providers} />
              </div>
            )
          )}

          {tab === 1 && (
            !models || models.state !== "ok" ? <PanelState panel={models ?? { state: "unavailable", source: "unknown", window_days: null, computed_at: "", reason: "model data did not load" }} emptyTitle="No model data" /> : (
              <div>
                <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
                  <input className="input-field" style={{ width: 200 }} placeholder="Filter models..." value={modelFilter} onChange={(e) => setModelFilter(e.target.value)} />
                  <select className="input-field" style={{ width: 140 }} value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
                    <option value="all">All providers</option>
                    {providerNames.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>{sorted.length} of {modelList.length}</span>
                </div>
                <Card>
                  <div style={{ overflow: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 12 }}>
                      <thead>
                        <tr>
                          <SortableHeader label="Model" field="model" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Provider" field="provider" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Tier" field="tier" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Quality" field="quality" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <SortableHeader label="Speed" field="speed" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                          <th style={{ textAlign: "left", padding: "8px 10px", color: "var(--pencil)", fontWeight: 600, fontSize: 12, textTransform: "uppercase", borderBottom: "1.3px solid var(--rule)" }}>Modality</th>
                          <th style={{ textAlign: "left", padding: "8px 10px", color: "var(--pencil)", fontWeight: 600, fontSize: 12, textTransform: "uppercase", borderBottom: "1.3px solid var(--rule)" }}>Strengths</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sorted.map((m) => (
                          <tr key={m.model} style={{ borderBottom: "1px solid var(--rule)", opacity: m.available ? 1 : 0.5 }}>
                            <td style={{ padding: "6px 10px", fontWeight: 600, whiteSpace: "nowrap" }}>{m.model}</td>
                            <td style={{ padding: "6px 10px", color: "var(--pencil)" }}>{m.provider}</td>
                            <td style={{ padding: "6px 10px" }}>
                              {m.tier ? (
                                <span style={{ fontFamily: "var(--mono)", fontSize: 12, padding: "2px 6px", borderRadius: 3, border: `1px solid ${tierColor[m.tier] || "var(--rule)"}`, color: tierColor[m.tier] || "var(--pencil)" }}>{m.tier}</span>
                              ) : <span style={{ color: "var(--pencil)" }}>n/a</span>}
                            </td>
                            <td style={{ padding: "6px 10px" }}>
                              {m.quality === null || m.quality === undefined ? (
                                <span style={{ color: "var(--pencil)" }}>n/a</span>
                              ) : (
                                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                  <div style={{ width: 50, height: 5, borderRadius: 3, background: "var(--rule)", overflow: "hidden" }}>
                                    <div style={{ height: "100%", borderRadius: 3, background: "var(--accent)", width: `${m.quality * 100}%` }} />
                                  </div>
                                  <span style={{ fontSize: 12 }}>{(m.quality * 100).toFixed(0)}%</span>
                                </div>
                              )}
                            </td>
                            <td style={{ padding: "6px 10px", color: "var(--pencil)" }}>{m.speed ? `${m.speed} t/s` : "n/a"}</td>
                            <td style={{ padding: "6px 10px", color: "var(--pencil)", fontSize: 12 }}>{m.modality || "-"}</td>
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
                <ProvenanceFooter panel={models} />
              </div>
            )
          )}

          {tab === 2 && (
            // #380: outcomes are not measured anywhere (LiteLLM exposes no
            // aggregated success/failure endpoint), so this tab is explicitly
            // unavailable. It used to render a hard-coded zeroed scoreboard
            // that read as "0 requests, everything failing".
            !outcomes ? (
              <PanelState
                panel={{ state: "unavailable", source: "unknown", window_days: null, computed_at: "", reason: "outcome data did not load" }}
                emptyTitle="No outcome data"
              />
            ) : (
              <div>
                <PanelState panel={outcomes} emptyTitle="No outcome data" />
                <ProvenanceFooter panel={outcomes} />
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}
