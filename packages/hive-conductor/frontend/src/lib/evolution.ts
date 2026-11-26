/** Evolution engine wire shapes and snapshot reads (services/evolution.py).
 * Under `lib/` for typed-client. */

const API = "/v1/evolution";

export type Genome = {
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

export type EvoStatus = {
  running: boolean;
  execution_available: boolean;
  availability: "executable" | "degraded" | "unavailable";
  availability_reason: string | null;
  domain_state_only: boolean;
  cycle_count: number;
  population_size: number;
  last_error: string | null;
  last_run_id: string | null;
  last_run_status: string | null;
  tournament: { total_battles: number; total_genomes_rated: number; benchmarks_tracked: number };
};

export type LeaderEntry = {
  genome_id: string;
  avg_elo: number;
  total_battles: number;
  win_rate: number;
};

export type EvolutionSnapshot = {
  status?: EvoStatus;
  population?: Genome[];
  /** Parsed when the champion endpoint answered ok; absent means "keep the
   * previous champion" exactly as the page always has. */
  champion?: Genome | null;
  leaderboard?: LeaderEntry[];
};

/** The four snapshot reads in one parallel batch. A member that fails keeps
 * its section absent so the page holds its previous value for it — the same
 * per-section silent-skip semantics the page has always had. */
export async function fetchEvolutionSnapshot(): Promise<EvolutionSnapshot> {
  const [sRes, pRes, cRes, lRes] = await Promise.all([
    fetch(`${API}/status`),
    fetch(`${API}/population`),
    fetch(`${API}/champion`),
    fetch(`${API}/tournament/leaderboard`),
  ]);
  const snap: EvolutionSnapshot = {};
  if (sRes.ok) snap.status = (await sRes.json()) as EvoStatus;
  if (pRes.ok) snap.population = (await pRes.json()) as Genome[];
  if (cRes.ok) {
    const cd = (await cRes.json()) as { genome?: Genome | null };
    snap.champion = cd.genome ?? null;
  }
  if (lRes.ok) snap.leaderboard = (await lRes.json()) as LeaderEntry[];
  return snap;
}

/** Kick one evolution cycle; the page refreshes after it returns. */
export async function triggerEvolutionCycle(): Promise<void> {
  await fetch(`${API}/cycle`, { method: "POST" });
}

/** Seed the population with `count` genomes named evolved-*. */
export async function seedEvolutionPopulation(count: number): Promise<void> {
  await fetch(`${API}/seed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count, base_name: "evolved" }),
  });
}
