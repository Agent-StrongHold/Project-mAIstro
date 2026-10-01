import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Square, RefreshCw, Check, X, GitPullRequest, FileCode } from "lucide-react";

import { PageHeader } from "../components/shared";

const API = "/v1/rsi";

type RsiStatus = { available: boolean; active_runs: number; total_runs: number };
type ModelOption = { id: string; label: string; tier: string };
// A test command the SERVER holds, as its argument vector (#305). The page
// shows the argv so an operator can see exactly what a profile runs; it
// sends only the name, and the backend never accepts a command.
type TestProfile = { name: string; argv: string[] };

type Run = {
  run_id: string;
  mode: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  cycles: number;
  promotions: number;
  last_error: string | null;
  summary: string | null;
  config: Record<string, unknown>;
  report_dir: string | null;
};

type Review = {
  sha: string;
  target: string;
  kind: string;
  predicted_p: number;
  theta: number;
  note: string;
  features: Record<string, number>;
  resolved: boolean;
  decision: string | null;
  diff?: string;
  diff_lines?: number;
};


const STATUS_TONE: Record<string, string> = {
  running: "text-amber-400",
  completed: "text-emerald-400",
  errored: "text-red-400",
  stopped: "text-slate-400",
};

// ─── resilient polling (#359) ───────────────────────────────────────────────
// This page used to run two bare `setInterval` + `Promise.all` loops with no
// catch: one backend outage produced an unhandled rejection every tick,
// forever, at a fixed cadence, with in-flight requests outliving the page and
// no notion of tab visibility. Everything below gives both loops one
// contract:
//   - failures are caught into a visible health state (unreachable /
//     server-error / unauthorized, each rendered distinctly) and NEVER clear
//     the last known data;
//   - failure delays grow exponentially (interval * 2^failures), are capped,
//     and carry jitter; any success resets the cadence;
//   - the loop pauses while the tab is hidden or the browser is offline and
//     re-kicks on visibilitychange / online;
//   - at most one poll is in flight, and the next is scheduled only after it
//     settles — overlap is impossible by construction;
//   - an unmount (or subject switch) aborts the in-flight request.

const PAGE_POLL_MS = 5_000;
const REVIEWS_POLL_MS = 4_000;
const MAX_BACKOFF_MS = 60_000;
/** Poll requests get a tighter ceiling than the shared client's 30s (#1423):
 * a stalled endpoint must delay the loop, not hang it. Fires the same abort
 * path as an unmount, so a hung request classifies as unreachable and the
 * loop keeps going under backoff. */
const POLL_TIMEOUT_MS = 15_000;

/** Why a poll cycle failed, ranked by how the UI presents it. */
type FailureKind = "unauthorized" | "server-error" | "unreachable";
type PollHealth = "loading" | "ok" | FailureKind;

const FAILURE_RANK: Record<FailureKind, number> = {
  unauthorized: 3,
  "server-error": 2,
  unreachable: 1,
};

/** An HTTP status a poll can name. Transport failures carry no status, so
 * they stay unclassified and classify as "unreachable". */
class PollHttpError extends Error {
  constructor(
    readonly kind: FailureKind,
    readonly status: number,
    readonly path: string,
  ) {
    super(`${path} answered ${status}`);
    this.name = "PollHttpError";
  }
}

function classifyFailure(err: unknown): FailureKind {
  if (err instanceof PollHttpError) return err.kind;
  // fetch()'s TypeError (offline, refused, CORS) and an abort (unmount or
  // the timeout above) carry no HTTP answer: the service is unreachable,
  // which is its own state — never "server error", never "not installed".
  return "unreachable";
}

function worstFailure(a: FailureKind | null, b: FailureKind | null): FailureKind | null {
  if (!a || !b) return a ?? b;
  return FAILURE_RANK[a] >= FAILURE_RANK[b] ? a : b;
}

/** One GET for JSON, with the caller's lifecycle signal composed with the
 * poll timeout: whichever aborts first wins, and the composition is wired by
 * hand (no AbortSignal.any) to stay inside the build's browser baseline. */
async function fetchJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const stop = () => controller.abort();
  const timeout = window.setTimeout(stop, POLL_TIMEOUT_MS);
  signal.addEventListener("abort", stop, { once: true });
  try {
    const res = await fetch(path, { credentials: "same-origin", signal: controller.signal });
    // 401/403 mean the SESSION cannot see RSI — a different problem, and a
    // different message, than the service being down or broken (#359).
    if (res.status === 401 || res.status === 403) throw new PollHttpError("unauthorized", res.status, path);
    if (!res.ok) throw new PollHttpError("server-error", res.status, path);
    return (await res.json()) as T;
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener("abort", stop);
  }
}

/** Apply a settled endpoint result to its setter, or surface its failure.
 * Callers aggregate endpoints with Promise.allSettled so one dead endpoint
 * degrades the page instead of erasing it (the Topology lesson, per-endpoint). */
function outcome<T>(settled: PromiseSettledResult<T>, apply: (value: T) => void): FailureKind | null {
  if (settled.status === "fulfilled") {
    apply(settled.value);
    return null;
  }
  return classifyFailure(settled.reason);
}

/** One self-rescheduling poll loop. `poll` applies fresh data and returns the
 * worst failure kind it hit (null = healthy); the hook tracks health and
 * exposes a manual `refresh` that shares the loop's guards and accounting. */
function useResilientPoll(
  poll: (signal: AbortSignal) => Promise<FailureKind | null>,
  options: { intervalMs: number; key?: string | null; enabled?: boolean },
): { health: PollHealth; refresh: () => void } {
  const { intervalMs, key, enabled = true } = options;
  // Re-arming on a new subject resets health during render (React's
  // recommended key-reset pattern): the previous subject's failure banner
  // must never show while the new subject's first poll is unanswered.
  const [armedKey, setArmedKey] = useState(key);
  const [health, setHealth] = useState<PollHealth>("loading");
  if (armedKey !== key) {
    setArmedKey(key);
    setHealth("loading");
  }
  const pollRef = useRef(poll);
  useEffect(() => {
    pollRef.current = poll;
  });
  const runRef = useRef<((manual: boolean) => void) | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let inFlight = false;
    let failures = 0;
    let timer: number | null = null;
    let controller: AbortController | null = null;

    // Bounded exponential backoff: interval * 2^failures capped at
    // MAX_BACKOFF_MS, taken with 50–100% jitter so a fleet of clients never
    // re-syncs against a recovering backend. `failures` resets to 0 on any
    // success, restoring the base cadence.
    const backoffDelayMs = () => {
      const base = Math.min(intervalMs * 2 ** failures, MAX_BACKOFF_MS);
      return base / 2 + Math.random() * (base / 2);
    };

    const run = async (manual: boolean) => {
      if (cancelled || inFlight) return;
      // Hidden or offline pauses the loop: return WITHOUT rescheduling. The
      // resume listener re-kicks it when the tab comes back or the network
      // does. A manual refresh is an explicit act, so it runs regardless.
      if (!manual && (document.hidden || !navigator.onLine)) return;
      // A manual refresh supersedes any armed backoff timer: this run's own
      // finally rearms the loop from the fresh result, and a leftover timer
      // would fire an extra poll at the stale (possibly backoff-inflated)
      // delay on top of that schedule.
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
      inFlight = true;
      controller = new AbortController();
      try {
        const failure = await pollRef.current(controller.signal);
        if (!cancelled) {
          failures = failure ? failures + 1 : 0;
          setHealth(failure ?? "ok");
        }
      } catch (err) {
        if (!cancelled) {
          failures += 1;
          setHealth(classifyFailure(err));
        }
      } finally {
        inFlight = false;
        controller = null;
        // The next poll exists only after this one settled — overlap is
        // impossible by construction — and its delay carries the backoff.
        if (!cancelled) timer = window.setTimeout(() => void run(false), backoffDelayMs());
      }
    };
    runRef.current = (manual: boolean) => void run(manual);

    const resume = () => {
      if (cancelled || document.hidden || !navigator.onLine) return;
      // Poll now instead of waiting out a possibly backoff-inflated timer.
      // If a poll is in flight run() no-ops and its finally re-arms the loop.
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      void run(false);
    };
    const onVisibilityChange = () => {
      if (!document.hidden) resume();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("online", resume);

    void run(false);

    return () => {
      cancelled = true;
      runRef.current = null;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("online", resume);
      if (timer !== null) window.clearTimeout(timer);
      // No request outlives the page: an in-flight poll dies here.
      controller?.abort();
    };
  }, [enabled, intervalMs, key]);

  const refresh = useCallback(() => {
    runRef.current?.(true);
  }, []);

  return { health, refresh };
}

export default function RSI() {
  const [status, setStatus] = useState<RsiStatus | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [profiles, setProfiles] = useState<TestProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState("");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [reviews, setReviews] = useState<{ kept: Review[]; flagged: Review[] }>({
    kept: [],
    flagged: [],
  });
  const [rlphd, setRlphd] = useState<Record<string, unknown> | null>(null);

  // start-run form
  const [repoPath, setRepoPath] = useState("");
  const [testProfile, setTestProfile] = useState("");
  const [model, setModel] = useState("glm-4.7");
  const [cycles, setCycles] = useState(10);
  const [agentTurns, setAgentTurns] = useState(2);
  const [fitness, setFitness] = useState(true);
  const [genomeModels, setGenomeModels] = useState("");
  const [rosterSize, setRosterSize] = useState(1);
  const [scout, setScout] = useState(true);

  // Page dashboard poll: status, runs, models, test profiles — under the
  // resilient contract (#359). allSettled per endpoint: a successful response
  // still lands during a partial outage, and the worst failure across the
  // four endpoints becomes the page's health state.
  const loadDashboard = useCallback(async (signal: AbortSignal): Promise<FailureKind | null> => {
    setLoading(true);
    try {
      const [s, r, m, p] = await Promise.allSettled([
        fetchJson<RsiStatus>(`${API}/status`, signal),
        fetchJson<Run[]>(`${API}/runs`, signal),
        fetchJson<{ models: ModelOption[] }>(`${API}/models`, signal),
        fetchJson<{ profiles: TestProfile[] }>(`${API}/test-profiles`, signal),
      ]);
      let worst = worstFailure(null, outcome(s, (value) => setStatus(value)));
      worst = worstFailure(
        worst,
        outcome(r, (list) => setRuns([...list].sort((a, b) => (a.started_at < b.started_at ? 1 : -1)))),
      );
      worst = worstFailure(worst, outcome(m, (data) => setModels(data.models || [])));
      worst = worstFailure(
        worst,
        outcome(p, (data) => {
          const list = (data.profiles || []) as TestProfile[];
          setProfiles(list);
          // Only default to a profile that exists. Pre-selecting a name the
          // deployment does not offer would make the form look ready and the
          // request fail.
          setTestProfile((current) => (list.some((x) => x.name === current) ? current : list[0]?.name ?? ""));
        }),
      );
      return worst;
    } finally {
      setLoading(false);
    }
  }, []);
  const { health: pageHealth, refresh } = useResilientPoll(loadDashboard, { intervalMs: PAGE_POLL_MS });

  // Selected run's patch feed, same contract (#359). `key` re-arms the loop
  // per run; the effect below drops the previous run's patches so a slow feed
  // can never present stale rows as this run's.
  const loadReviews = useCallback(
    async (signal: AbortSignal): Promise<FailureKind | null> => {
      if (!selectedRun) return null;
      const [rev, rlp] = await Promise.allSettled([
        fetchJson<{ kept: Review[]; flagged: Review[] }>(`${API}/runs/${selectedRun}/reviews`, signal),
        fetchJson<Record<string, unknown>>(`${API}/runs/${selectedRun}/rlphd`, signal),
      ]);
      // Aborting is how a run switch (key change) or unmark supersedes this
      // loop. A batch that straddles the switch — one endpoint already
      // fulfilled, the other rejected by the abort — must not re-apply the
      // old run's rows over the new run's render-phase reset: drop it whole.
      if (signal.aborted) return null;
      let worst = worstFailure(null, outcome(rev, (data) => setReviews(data)));
      worst = worstFailure(worst, outcome(rlp, (data) => setRlphd(data)));
      return worst;
    },
    [selectedRun],
  );
  const { health: reviewsHealth } = useResilientPoll(loadReviews, {
    intervalMs: REVIEWS_POLL_MS,
    key: selectedRun,
    enabled: selectedRun !== null,
  });

  // A newly selected run starts with a clean feed (render-phase reset, keyed
  // on the selection): a slow patch feed must never present the previous
  // run's rows as this run's.
  const [feedsRun, setFeedsRun] = useState(selectedRun);
  if (feedsRun !== selectedRun) {
    setFeedsRun(selectedRun);
    setReviews({ kept: [], flagged: [] });
    setRlphd(null);
  }

  const startRun = async () => {
    if (!repoPath || !testProfile) return;
    setStartError("");
    setBusy(true);
    try {
      const resp = await fetch(`${API}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "cleanup",
          repo_path: repoPath,
          test_profile: testProfile,
          cycles,
          agent_turns: agentTurns,
          model,
          fitness,
          genome_models: genomeModels || undefined,
          roster_size: rosterSize,
          scout,
        }),
      });
      if (resp.ok) {
        const run = await resp.json();
        setSelectedRun(run.run_id);
        refresh();
      } else {
        // The backend refuses a run it cannot contain (#305). Showing the
        // refusal beats a button that appears to do nothing: the operator
        // needs to know the isolated wrapper is the way to run this.
        const body = await resp.json().catch(() => ({}));
        setStartError(body.detail || `start refused (${resp.status})`);
      }
    } finally {
      setBusy(false);
    }
  };

  const decide = async (sha: string, decision: "approve" | "deny", reason?: string) => {
    if (!selectedRun) return;
    const resp = await fetch(`${API}/runs/${selectedRun}/reviews/${sha}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reason, repo_path: repoPath }),
    });
    if (resp.ok) {
      const result = await resp.json();
      // show what Ralph learned
      if (result.weight_delta?.prediction_explanation) {
        const expl = result.weight_delta.prediction_explanation
          .filter((e: { contribution: number }) => Math.abs(e.contribution) > 0.001)
          .map((e: { feature: string; contribution: number }) => `${e.feature}: ${e.contribution > 0 ? "+" : ""}${e.contribution.toFixed(3)}`)
          .join(", ");
        const thetaDelta = result.weight_delta.theta.after - result.weight_delta.theta.before;
        const weightChanges = Object.entries(
          result.weight_delta.weights as Record<string, { before: number; after: number }>,
        )
          .filter(([, v]) => Math.abs(v.after - v.before) > 0.0001)
          .map(([k, v]) => `${k} ${v.before.toFixed(4)}→${v.after.toFixed(4)}`)
          .join(", ");
        console.log(`Ralph learned: θ ${result.weight_delta.theta.before.toFixed(3)}→${result.weight_delta.theta.after.toFixed(3)} (Δ${thetaDelta >= 0 ? "+" : ""}${thetaDelta.toFixed(4)}), weights: ${weightChanges}`);
        console.log(`Prediction was: ${expl}`);
      }
    }
  };

  const activeRun = runs.find((r) => r.run_id === selectedRun);
  const allReviews = [...reviews.kept, ...reviews.flagged].sort((a, b) =>
    a.sha < b.sha ? 1 : -1,
  );

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader
        title="RSI — Recursive Self-Improvement"
        subtitle="Start a cleanup run, review patches as they land, approve/deny to train Ralph."
      />

      {/* status + Ralph */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-white/10 bg-slate-900/60 px-4 py-3 text-sm">
        <span className={`h-2 w-2 rounded-full ${status ? (status.available ? "bg-emerald-400" : "bg-red-400") : "bg-slate-500"}`} />
        {/* "Not installed" is a fact only a real status may state (#359): a
            poll that cannot answer renders as unknown, never as unavailable. */}
        <span>{status ? (status.available ? "maistro-rsi available" : "maistro-rsi not installed") : "RSI status unknown"}</span>
        <span className="text-slate-500">·</span>
        <span>{status?.active_runs ?? 0} active</span>
        {rlphd && (
          <>
            <span className="text-slate-500">·</span>
            <span className="text-violet-300">
              Ralph θ = {Object.entries(rlphd.thetas || {}).map(([k, v]) => `${k}=${(v as number).toFixed(3)}`).join(", ") || "cold-start"}
            </span>
          </>
        )}
        <button onClick={refresh} className="ml-auto inline-flex items-center gap-1 rounded px-2 py-1 text-slate-300 hover:bg-white/10">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Poll health (#359): the failure states are rendered distinctly from
          each other and from empty, and none of them clears the last known
          data rendered above. */}
      {pageHealth !== "ok" && pageHealth !== "loading" && (
        <p
          role="alert"
          data-testid="rsi-poll-health"
          data-health={pageHealth}
          className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
        >
          {pageHealth === "unreachable" &&
            "Can't reach the RSI service — showing last known values and retrying with backoff."}
          {pageHealth === "server-error" &&
            "The RSI service is returning server errors — showing last known values and retrying with backoff."}
          {pageHealth === "unauthorized" &&
            "Your session can't access RSI (unauthorized) — sign in again to resume live updates. Last known values are kept."}
        </p>
      )}

      {/* start-run form */}
      <section className="space-y-3 rounded-lg border border-white/10 bg-slate-900/60 p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Start a cleanup run</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="text-xs text-slate-400 md:col-span-2">
            Repo path
            <input className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={repoPath} onChange={(e) => setRepoPath(e.target.value)} placeholder="C:/maistro-develop" />
          </label>
          <label className="text-xs text-slate-400">
            Model
            <select className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              <option value="oss120-cerebras">Cerebras gpt-oss-120b</option>
            </select>
          </label>
          <label className="text-xs text-slate-400 md:col-span-3">
            Test profile (exit 0 ⇔ healthy)
            <select className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={testProfile} onChange={(e) => setTestProfile(e.target.value)}>
              {profiles.length === 0 && <option value="">no test profiles configured</option>}
              {profiles.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
            <span className="mt-1 block font-mono text-[11px] text-slate-500">
              {profiles.find((p) => p.name === testProfile)?.argv.join(" ") ?? "—"}
            </span>
          </label>
          <label className="text-xs text-slate-400">
            Cycles
            <input type="number" min={1} className="mt-1 w-20 rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={cycles} onChange={(e) => setCycles(Number(e.target.value) || 1)} />
          </label>
          <label className="text-xs text-slate-400">
            Agent turns
            <input type="number" min={1} max={6} className="mt-1 w-20 rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={agentTurns} onChange={(e) => setAgentTurns(Number(e.target.value) || 1)} />
          </label>
          <label className="text-xs text-slate-400">
            Roster size
            <input type="number" min={1} max={5} className="mt-1 w-20 rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={rosterSize} onChange={(e) => setRosterSize(Number(e.target.value) || 1)} />
          </label>
          <label className="text-xs text-slate-400 md:col-span-2">
            Genome models (comma-separated, optional)
            <input className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm" value={genomeModels} onChange={(e) => setGenomeModels(e.target.value)} placeholder="glm-4.7,glm-5.2,oss120-cerebras" />
          </label>
          <div className="flex items-end gap-4 text-xs text-slate-400">
            <label className="flex items-center gap-2"><input type="checkbox" checked={fitness} onChange={(e) => setFitness(e.target.checked)} /> Fitness scorecard</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={scout} onChange={(e) => setScout(e.target.checked)} /> Scout</label>
          </div>
        </div>
        <button onClick={startRun} disabled={busy || !repoPath || !testProfile} className="inline-flex items-center gap-2 rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
          <Play className="h-4 w-4" />{busy ? "Starting…" : "Start run"}
        </button>
        {startError && (
          <p className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            {startError}
          </p>
        )}
      </section>

      {/* runs list */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Runs</h2>
        {/* Empty (healthy, zero runs) is distinct from loading and from a
            poll that cannot answer (#359). */}
        {runs.length === 0 && (
          <p className="text-sm text-slate-500">
            {pageHealth === "ok"
              ? "No runs yet."
              : pageHealth === "loading"
                ? "Loading runs…"
                : "No runs loaded yet — see the poll status above."}
          </p>
        )}
        {runs.map((r) => (
          <div key={r.run_id} className="flex items-stretch gap-2">
            <button
              type="button"
              aria-pressed={selectedRun === r.run_id}
              onClick={() => setSelectedRun(r.run_id)}
              className={`min-w-0 flex-1 rounded-lg border p-3 text-left text-sm transition ${
                selectedRun === r.run_id ? "border-sky-500 bg-sky-950/40" : "border-white/10 bg-slate-900/60 hover:bg-slate-800/60"
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={`font-mono text-xs ${STATUS_TONE[r.status] ?? "text-slate-400"}`}>{r.status}</span>{" "}
                <span className="text-slate-500">{r.run_id}</span>{" "}
                <span className="ml-auto text-slate-300">{r.promotions}/{r.cycles} promoted</span>
              </div>
              {r.last_error && <p className="mt-1 truncate text-xs text-red-400">{r.last_error}</p>}
            </button>
            {r.status === "running" && (
              <button
                type="button"
                aria-label={`Stop run ${r.run_id}`}
                title={`Stop run ${r.run_id}`}
                onClick={() => { fetch(`${API}/runs/${r.run_id}/stop`, { method: "POST" }); }}
                className="rounded-lg border border-white/10 bg-slate-900/60 px-3 text-red-300 hover:bg-slate-800/60"
              >
                <Square className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
        ))}
      </section>

      {/* patch feed for selected run */}
      {selectedRun && activeRun && (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Patches — {activeRun.run_id}
            </h2>
            <span className="text-xs text-slate-500">{allReviews.length} total</span>
            <span className="text-xs text-emerald-400">{allReviews.filter((r) => r.decision === "approve").length} approved</span>
            <span className="text-xs text-red-400">{allReviews.filter((r) => r.decision === "deny").length} denied</span>
            <span className="text-xs text-amber-400">{allReviews.filter((r) => !r.resolved).length} pending</span>
          </div>

          {reviewsHealth !== "ok" && reviewsHealth !== "loading" && (
            <p
              role="alert"
              data-testid="rsi-reviews-health"
              data-health={reviewsHealth}
              className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
            >
              {reviewsHealth === "unreachable" &&
                "Can't reach the patch feed for this run — retrying with backoff; the patches shown are the last known ones."}
              {reviewsHealth === "server-error" &&
                "The patch feed is returning server errors — retrying with backoff; the patches shown are the last known ones."}
              {reviewsHealth === "unauthorized" &&
                "Your session can't read this run's patch feed (unauthorized) — sign in again to resume."}
            </p>
          )}

          {allReviews.length === 0 && (
            <p className="text-sm text-slate-500">
              {activeRun.status === "running" ? "Waiting for the first promotion…" : "No promotions in this run."}
            </p>
          )}

          {allReviews.map((rev) => (
            <PatchCard key={rev.sha} review={rev} onDecide={decide} />
          ))}
        </section>
      )}
    </div>
  );
}

function PatchCard({ review, onDecide }: { review: Review; onDecide: (sha: string, d: "approve" | "deny", reason?: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [reason, setReason] = useState("");
  const [showReason, setShowReason] = useState(false);
  const tone = review.decision === "approve" ? "border-emerald-600/40" : review.decision === "deny" ? "border-red-600/40" : "border-white/10";

  // feature attribution — WHY Ralph kept or reverted this
  const featureRows = Object.entries(review.features || {})
    .map(([k, v]) => ({ feature: k, value: v }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

  return (
    <div className={`rounded-lg border ${tone} bg-slate-900/60 p-3 text-sm`}>
      <div className="flex items-center gap-3">
        <FileCode className="h-4 w-4 text-slate-500" />
        <span className="font-mono text-xs text-slate-400">{review.sha.slice(0, 12)}</span>
        <span className="truncate text-slate-300">{review.target}</span>
        <span className="ml-auto text-xs text-slate-500">p={review.predicted_p.toFixed(3)} θ={review.theta.toFixed(3)}</span>
        {review.resolved ? (
          <span className={`text-xs ${review.decision === "approve" ? "text-emerald-400" : "text-red-400"}`}>
            {review.decision === "approve" ? <><Check className="inline h-3.5 w-3.5" /> Approved</> : <><X className="inline h-3.5 w-3.5" /> Denied</>}
          </span>
        ) : (
          <div className="flex gap-2">
            <button onClick={() => onDecide(review.sha, "approve", reason || undefined)} className="inline-flex items-center gap-1 rounded bg-emerald-600/80 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500">
              <Check className="h-3.5 w-3.5" /> Approve + PR
            </button>
            <button onClick={() => setShowReason(!showReason)} className="inline-flex items-center gap-1 rounded bg-red-600/80 px-3 py-1 text-xs font-medium text-white hover:bg-red-500">
              <X className="h-3.5 w-3.5" /> Deny
            </button>
          </div>
        )}
      </div>

      {/* feature breakdown — WHY Ralph predicted this way */}
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
        <span>Features:</span>
        {featureRows.map((f) => (
          <span key={f.feature} className="rounded bg-slate-800/60 px-1.5 py-0.5 font-mono">
            {f.feature}={f.value.toFixed(2)}
          </span>
        ))}
      </div>

      {showReason && !review.resolved && (
        <div className="mt-2 flex gap-2">
          <input
            className="flex-1 rounded border border-white/10 bg-slate-950 px-2 py-1 text-xs"
            placeholder="Why deny? (optional — helps Ralph learn the pattern)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button onClick={() => onDecide(review.sha, "deny", reason || undefined)} className="rounded bg-red-600 px-3 py-1 text-xs text-white">
            Confirm deny
          </button>
        </div>
      )}

      <p className="mt-1 text-xs text-slate-500">{review.note}</p>
      {review.diff && (
        <button onClick={() => setExpanded(!expanded)} className="mt-1 text-xs text-sky-400 hover:underline">
          {expanded ? "Hide diff" : `Show diff (${review.diff_lines ?? 0} lines)`}
        </button>
      )}
      {expanded && review.diff && (
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-slate-950 p-2 text-xs text-slate-400">{review.diff}</pre>
      )}
      {review.decision === "approve" && review.resolved && (
        <p className="mt-1 text-xs text-emerald-400"><GitPullRequest className="inline h-3.5 w-3.5" /> PR created</p>
      )}
    </div>
  );
}
