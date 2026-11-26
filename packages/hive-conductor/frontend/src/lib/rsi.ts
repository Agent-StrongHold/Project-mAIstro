/** RSI (Recursive Self-Improvement) wire shapes, resilient poll client, and
 * run operations (services/rsi*.py). Under `lib/` for typed-client: the
 * page imports these instead of declaring them locally or fetching inline. */

const API = "/v1/rsi";

export type RsiStatus = { available: boolean; active_runs: number; total_runs: number };
export type ModelOption = { id: string; label: string; tier: string };
// A test command the SERVER holds, as its argument vector (#305). The page
// shows the argv so an operator can see exactly what a profile runs; it
// sends only the name, and the backend never accepts a command.
export type TestProfile = { name: string; argv: string[] };

export type Run = {
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

export type Review = {
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

/** Why a poll cycle failed, ranked by how the UI presents it. */
export type FailureKind = "unauthorized" | "server-error" | "unreachable";
export type PollHealth = "loading" | "ok" | FailureKind;

const FAILURE_RANK: Record<FailureKind, number> = {
  unauthorized: 3,
  "server-error": 2,
  unreachable: 1,
};

/** An HTTP status a poll can name. Transport failures carry no status, so
 * they stay unclassified and classify as "unreachable". */
export class PollHttpError extends Error {
  constructor(
    readonly kind: FailureKind,
    readonly status: number,
    readonly path: string,
  ) {
    super(`${path} answered ${status}`);
    this.name = "PollHttpError";
  }
}

export function classifyFailure(err: unknown): FailureKind {
  if (err instanceof PollHttpError) return err.kind;
  // fetch()'s TypeError (offline, refused, CORS) and an abort (unmount or
  // the timeout above) carry no HTTP answer: the service is unreachable,
  // which is its own state — never "server error", never "not installed".
  return "unreachable";
}

export function worstFailure(a: FailureKind | null, b: FailureKind | null): FailureKind | null {
  if (!a || !b) return a ?? b;
  return FAILURE_RANK[a] >= FAILURE_RANK[b] ? a : b;
}

/** Poll requests get a tighter ceiling than the shared client's 30s (#1423):
 * a stalled endpoint must delay the loop, not hang it. Fires the same abort
 * path as an unmount, so a hung request classifies as unreachable and the
 * loop keeps going under backoff. */
const POLL_TIMEOUT_MS = 15_000;

/** One GET for JSON, with the caller's lifecycle signal composed with the
 * poll timeout: whichever aborts first wins, and the composition is wired by
 * hand (no AbortSignal.any) to stay inside the build's browser baseline. */
export async function fetchJson<T>(path: string, signal: AbortSignal): Promise<T> {
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
export function outcome<T>(settled: PromiseSettledResult<T>, apply: (value: T) => void): FailureKind | null {
  if (settled.status === "fulfilled") {
    apply(settled.value);
    return null;
  }
  return classifyFailure(settled.reason);
}

/** Body of POST /v1/rsi/runs: the server holds the test command (#305), so
 * the client names only the profile. */
export type RsiRunRequest = {
  mode: string;
  repo_path: string;
  test_profile: string;
  cycles: number;
  agent_turns: number;
  model: string;
  fitness: boolean;
  genome_models?: string;
  roster_size: number;
  scout: boolean;
};

export type RsiStartOutcome =
  | { ok: true; runId: string }
  | { ok: false; detail: string };

/** Start a cleanup run. A refusal carries the backend's verbatim `detail`
 * when it sent one, so the operator sees why the run was refused (#305). */
export async function startRsiRun(request: RsiRunRequest): Promise<RsiStartOutcome> {
  const resp = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (resp.ok) {
    const run = (await resp.json()) as { run_id: string };
    return { ok: true, runId: run.run_id };
  }
  const body = (await resp.json().catch(() => ({}))) as { detail?: string };
  return { ok: false, detail: body.detail || `start refused (${resp.status})` };
}

/** What POST /runs/{id}/reviews/{sha} answers for an accepted decision. */
export type RsiReviewResult = {
  weight_delta?: {
    theta: { before: number; after: number };
    weights: Record<string, { before: number; after: number }>;
    prediction_explanation?: { contribution: number; feature?: string }[];
  };
};

/** Record an approve/deny training decision on one reviewed patch. */
export async function decideRsiReview(
  runId: string,
  sha: string,
  decision: "approve" | "deny",
  repoPath: string,
  reason?: string,
): Promise<RsiReviewResult | null> {
  const resp = await fetch(`${API}/runs/${runId}/reviews/${sha}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reason, repo_path: repoPath }),
  });
  if (!resp.ok) return null;
  return (await resp.json()) as RsiReviewResult;
}

/** Fire-and-forget stop, exactly as the page's stop button always issued it. */
export function stopRsiRun(runId: string): void {
  void fetch(`${API}/runs/${runId}/stop`, { method: "POST" });
}
