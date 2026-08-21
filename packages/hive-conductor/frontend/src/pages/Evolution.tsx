import { useCallback, useEffect, useState } from "react";

const API = "/v1/evolution";

import { PageHeader } from "../components/shared";

type Genome = {
  id: string;
  name: string;
  fitness_score: number | null;
  generation: number;
  eval_scores: Record<string, number>;
  topology: { nodes: { id: string; role: string; model: string; strategy: string; system_prompt: string }[] };
  harness_params: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  parent_a_id: string | null;
  parent_b_id: string | null;
};

type EvoStatus = {
  running: boolean;
  cycle_count: number;
  population_size: number;
  last_error: string | null;
  tournament: { total_battles: number; total_genomes_rated: number; benchmarks_tracked: number };
};

type LeaderEntry = {
  genome_id: string;
  avg_elo: number;
  total_battles: number;
  win_rate: number;
};

export default function Evolution() {
  const [status, setStatus] = useState<EvoStatus | null>(null);
  const [genomes, setGenomes] = useState<Genome[]>([]);
  const [champion, setChampion] = useState<Genome | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"overview" | "population" | "tournament">("overview");
  const [seedCount, setSeedCount] = useState(5);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, pRes, cRes, lRes] = await Promise.all([
        fetch(`${API}/status`),
        fetch(`${API}/population`),
        fetch(`${API}/champion`),
        fetch(`${API}/tournament/leaderboard`),
      ]);
      if (sRes.ok) setStatus(await sRes.json());
      if (pRes.ok) {
        const pop = await pRes.json();
        setGenomes(
          (pop as Genome[]).sort(
            (a, b) => (b.fitness_score ?? 0) - (a.fitness_score ?? 0),
          ),
        );
      }
      if (cRes.ok) {
        const cd = await cRes.json();
        setChampion(cd.genome ?? null);
      }
      if (lRes.ok) setLeaderboard(await lRes.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, [refresh]);

  const triggerCycle = async () => {
    setLoading(true);
    await fetch(`${API}/cycle`, { method: "POST" });
    await refresh();
  };

  const seedPop = async () => {
    await fetch(`${API}/seed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: seedCount, base_name: "evolved" }),
    });
    await refresh();
  };

  const fmt = (n: number | null | undefined) =>
    n == null ? "N/A" : n.toFixed(2);

  return (
    <div style={{ padding: 24, maxWidth: 1200 }}>
      <PageHeader title="Evolution Engine" subtitle="Automatically improve agents over time using genetic algorithms" helpHref="/docs#evolution" />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8 }}>
          {(["overview", "population", "tournament"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="btn"
              style={{
                background: tab === t ? "var(--accent)" : "var(--card)",
                color: tab === t ? "var(--paper)" : "var(--ink)",
                textTransform: "capitalize",
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
          <button onClick={seedPop} disabled={loading} className="btn">
            Seed {seedCount}
          </button>
          <input
            type="number"
            value={seedCount}
            onChange={(e) => setSeedCount(parseInt(e.target.value) || 1)}
            style={{ width: 60, padding: "4px 8px" }}
            min={1}
            max={50}
          />
          <button onClick={triggerCycle} disabled={loading} className="btn" style={{ background: "var(--accent)", color: "var(--paper)" }}>
            Run Cycle
          </button>
          <button onClick={refresh} disabled={loading} className="btn">
            Refresh
          </button>
        </div>
      </div>

      {tab === "overview" && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16, marginBottom: 24 }}>
            <StatCard label="Running" value={status?.running ? "Yes" : "No"} color={status?.running ? "var(--success)" : "var(--danger)"} />
            <StatCard label="Cycles" value={String(status?.cycle_count ?? 0)} />
            <StatCard label="Population" value={String(status?.population_size ?? 0)} />
            <StatCard label="Champion Fitness" value={fmt(champion?.fitness_score)} />
            <StatCard label="Tournament Battles" value={String(status?.tournament?.total_battles ?? 0)} />
            <StatCard label="Benchmarks Tracked" value={String(status?.tournament?.benchmarks_tracked ?? 0)} />
          </div>

          {status?.last_error && (
            <div style={{ padding: 12, background: "var(--danger)", color: "var(--paper)", borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
              Last error: {status.last_error}
            </div>
          )}

          {champion && (
            <div style={{ background: "var(--card)", borderRadius: 8, padding: 16, marginBottom: 16 }}>
              <h3 style={{ margin: "0 0 12px" }}>Champion: {champion.name || champion.id}</h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 13 }}>
                <div><strong>Fitness:</strong> {fmt(champion.fitness_score)}</div>
                <div><strong>Generation:</strong> {champion.generation}</div>
                <div><strong>Nodes:</strong> {champion.topology.nodes.length}</div>
                <div><strong>Elo:</strong> {fmt((champion.harness_params as Record<string, number>)?.avg_elo)}</div>
              </div>
              <div style={{ marginTop: 12 }}>
                <strong style={{ fontSize: 13 }}>Eval Scores:</strong>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
                  {Object.entries(champion.eval_scores).map(([bench, score]) => (
                    <span
                      key={bench}
                      style={{
                        background: score >= 0.5 ? "var(--success)" : score >= 0.3 ? "#f0ad4e" : "var(--danger)",
                        color: "var(--paper)",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                      }}
                    >
                      {bench}: {(score as number).toFixed(3)}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {genomes.length > 0 && (
            <div style={{ background: "var(--card)", borderRadius: 8, padding: 16 }}>
              <h3 style={{ margin: "0 0 12px" }}>Fitness Distribution</h3>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 120 }}>
                {genomes.slice(0, 30).map((g) => (
                  <div
                    key={g.id}
                    title={`${g.name || g.id}: ${fmt(g.fitness_score)}`}
                    style={{
                      width: Math.max(8, 100 / Math.min(genomes.length, 30)),
                      height: `${Math.max(2, ((g.fitness_score ?? 0) / 100) * 100)}%`,
                      background: g.id === champion?.id ? "var(--accent)" : "var(--success)",
                      borderRadius: 2,
                      transition: "height 0.3s",
                    }}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "population" && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid var(--border)" }}>
                <th style={{ padding: 8 }}>Name</th>
                <th style={{ padding: 8 }}>Fitness</th>
                <th style={{ padding: 8 }}>Gen</th>
                <th style={{ padding: 8 }}>Nodes</th>
                <th style={{ padding: 8 }}>Elo</th>
                <th style={{ padding: 8 }}>IFEval</th>
                <th style={{ padding: 8 }}>BFCL</th>
                <th style={{ padding: 8 }}>GAIA</th>
                <th style={{ padding: 8 }}>Passed</th>
              </tr>
            </thead>
            <tbody>
              {genomes.map((g) => {
                const passed = Object.values(g.eval_scores).filter((s) => s > 0.2).length;
                return (
                  <tr key={g.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: 8, fontFamily: "var(--mono)", fontSize: 11 }}>
                      {g.name || g.id.slice(0, 12)}
                    </td>
                    <td style={{ padding: 8, fontWeight: g.id === champion?.id ? 700 : 400 }}>
                      {fmt(g.fitness_score)}
                    </td>
                    <td style={{ padding: 8 }}>{g.generation}</td>
                    <td style={{ padding: 8 }}>{g.topology.nodes.length}</td>
                    <td style={{ padding: 8 }}>{fmt((g.harness_params as Record<string, number>)?.avg_elo)}</td>
                    <td style={{ padding: 8 }}>{(g.eval_scores.ifeval ?? 0).toFixed(3)}</td>
                    <td style={{ padding: 8 }}>{(g.eval_scores.bfcl ?? 0).toFixed(3)}</td>
                    <td style={{ padding: 8 }}>{(g.eval_scores.gaia ?? 0).toFixed(3)}</td>
                    <td style={{ padding: 8 }}>
                      <span style={{ color: passed >= 8 ? "var(--success)" : "var(--danger)" }}>{passed}/8</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {tab === "tournament" && (
        <div>
          <h3 style={{ marginBottom: 12 }}>Elo Leaderboard</h3>
          {leaderboard.length === 0 ? (
            <p style={{ opacity: 0.6, fontSize: 13 }}>No tournament battles yet. Run a cycle to populate.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "2px solid var(--border)" }}>
                  <th style={{ padding: 8 }}>Rank</th>
                  <th style={{ padding: 8 }}>Genome</th>
                  <th style={{ padding: 8 }}>Elo</th>
                  <th style={{ padding: 8 }}>Battles</th>
                  <th style={{ padding: 8 }}>Win Rate</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((entry, i) => (
                  <tr key={entry.genome_id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: 8 }}>{i + 1}</td>
                    <td style={{ padding: 8, fontFamily: "var(--mono)", fontSize: 11 }}>
                      {entry.genome_id.slice(0, 16)}
                    </td>
                    <td style={{ padding: 8, fontWeight: 600 }}>{entry.avg_elo.toFixed(0)}</td>
                    <td style={{ padding: 8 }}>{entry.total_battles}</td>
                    <td style={{ padding: 8 }}>
                      <span style={{ color: entry.win_rate >= 0.5 ? "var(--success)" : "var(--danger)" }}>
                        {(entry.win_rate * 100).toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "var(--card)", borderRadius: 8, padding: 16 }}>
      <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color ?? "var(--ink)" }}>{value}</div>
    </div>
  );
}
