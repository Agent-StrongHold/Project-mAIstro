import { useCallback, useEffect, useState } from "react";
import { Play, Square, RefreshCw, Check, X, GitPullRequest, FileCode } from "lucide-react";

import { PageHeader } from "../components/shared";

const API = "/v1/rsi";

type RsiStatus = { available: boolean; active_runs: number; total_runs: number };
type ModelOption = { id: string; label: string; tier: string };

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

export default function RSI() {
  const [status, setStatus] = useState<RsiStatus | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [reviews, setReviews] = useState<{ kept: Review[]; flagged: Review[] }>({
    kept: [],
    flagged: [],
  });
  const [rlphd, setRlphd] = useState<Record<string, unknown> | null>(null);

  // start-run form
  const [repoPath, setRepoPath] = useState("");
  const [testCmd, setTestCmd] = useState("");
  const [model, setModel] = useState("glm-4.7");
  const [cycles, setCycles] = useState(10);
  const [agentTurns, setAgentTurns] = useState(2);
  const [fitness, setFitness] = useState(true);
  const [genomeModels, setGenomeModels] = useState("");
  const [rosterSize, setRosterSize] = useState(1);
  const [scout, setScout] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r, m] = await Promise.all([
        fetch(`${API}/status`),
        fetch(`${API}/runs`),
        fetch(`${API}/models`),
      ]);
      if (s.ok) setStatus(await s.json());
      if (r.ok) {
        const list = (await r.json()) as Run[];
        setRuns(list.sort((a, b) => (a.started_at < b.started_at ? 1 : -1)));
      }
      if (m.ok) {
        const data = await m.json();
        setModels(data.models || []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  // poll reviews for selected run
  useEffect(() => {
    if (!selectedRun) return;
    const poll = async () => {
      const [rev, rlp] = await Promise.all([
        fetch(`${API}/runs/${selectedRun}/reviews`),
        fetch(`${API}/runs/${selectedRun}/rlphd`),
      ]);
      if (rev.ok) setReviews(await rev.json());
      if (rlp.ok) setRlphd(await rlp.json());
    };
    poll();
    const id = setInterval(poll, 4000);
    return () => clearInterval(id);
  }, [selectedRun]);

  const startRun = async () => {
    if (!repoPath || !testCmd) return;
    setBusy(true);
    try {
      const resp = await fetch(`${API}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "cleanup",
          repo_path: repoPath,
          test_command: testCmd,
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
        await refresh();
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
        <span className={`h-2 w-2 rounded-full ${status?.available ? "bg-emerald-400" : "bg-red-400"}`} />
        <span>{status?.available ? "maistro-rsi available" : "maistro-rsi not installed"}</span>
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
            Test command (exit 0 ⇔ healthy)
            <input className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-sm font-mono" value={testCmd} onChange={(e) => setTestCmd(e.target.value)} placeholder="python -m pytest packages/maistro-rsi/tests packages/maistro-evolve/tests -q" />
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
        <button onClick={startRun} disabled={busy || !repoPath || !testCmd} className="inline-flex items-center gap-2 rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
          <Play className="h-4 w-4" />{busy ? "Starting…" : "Start run"}
        </button>
      </section>

      {/* runs list */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Runs</h2>
        {runs.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
        {runs.map((r) => (
          <button
            key={r.run_id}
            onClick={() => setSelectedRun(r.run_id)}
            className={`w-full rounded-lg border p-3 text-left text-sm transition ${
              selectedRun === r.run_id ? "border-sky-500 bg-sky-950/40" : "border-white/10 bg-slate-900/60 hover:bg-slate-800/60"
            }`}
          >
            <div className="flex items-center gap-3">
              <span className={`font-mono text-xs ${STATUS_TONE[r.status] ?? "text-slate-400"}`}>{r.status}</span>
              <span className="text-slate-500">{r.run_id}</span>
              <span className="ml-auto text-slate-300">{r.promotions}/{r.cycles} promoted</span>
              {r.status === "running" && <span className="text-xs text-red-300" onClick={(e) => { e.stopPropagation(); fetch(`${API}/runs/${r.run_id}/stop`, { method: "POST" }); }}><Square className="h-3.5 w-3.5" /></span>}
            </div>
            {r.last_error && <p className="mt-1 truncate text-xs text-red-400">{r.last_error}</p>}
          </button>
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
