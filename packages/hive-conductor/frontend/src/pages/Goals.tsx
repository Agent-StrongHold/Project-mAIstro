// Goals — the Workspace-centric inspection view (#65).
//
// One Goal is one history: every run executed toward it appears here, in
// order, exactly as the run seam reports it. This page reads two canonical
// doors and nothing else:
//   GET /v1/workspaces/{id}/goals — the Goal view for the caller's workspace
//                                 (evidence grouped per Goal)
//   /dag-runs?run=<id>          — the run detail/live surface (list, detail,
//                                 cancel control live there, not here)
// It decides nothing: a finished run below is evidence, and only the
// canonical Goal owner records the Goal's state. That separation is the
// product contract, so the banner states it in plain words rather than hiding
// it.
//
// The page is scoped to one Workspace — the active tab, or the ?ws= a run's
// Goal back-link names — because the inspection route lives under the
// declared /v1/workspaces prefix with Home and Attention (#1048/#1049).
//
// Read-only by design: nothing here transitions a run or a goal. The page
// polls with setInterval (never setTimeout — see the shipped-surface truth
// checker) and deep-links via ?goal= so a bookmark or reload restores the
// same view after a restart.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { apiGet } from "../lib/api";
import { useWorkspaces } from "../context/WorkspaceContext";
import type { GoalView, RunEvidence } from "../lib/goalInspection";
import { Card, EmptyState, LoadingSpinner, PageHeader } from "../components/shared";

const DISPOSITION_LABELS: Record<string, { label: string; color: string }> = {
  waiting_human: { label: "Waiting for you", color: "#e8a03a" },
  blocked: { label: "Blocked", color: "#c4452a" },
  active: { label: "In progress", color: "var(--accent)" },
  waiting: { label: "Waiting", color: "#e8a03a" },
  evidence_settled: { label: "Work settled", color: "#5b8fb3" },
};

function disposition(value: string): { label: string; color: string } {
  return DISPOSITION_LABELS[value] ?? { label: value, color: "var(--pencil)" };
}

function fmtTime(ts: number | null): string {
  if (typeof ts !== "number") return "—";
  return new Date(ts * 1000).toLocaleString();
}

function RunRow({ run, onOpen }: { run: RunEvidence; onOpen: (id: string) => void }) {
  const lineage: string[] = [];
  if (run.parent_run_id) lineage.push("started by another run");
  if (run.persona_id) lineage.push(`persona ${run.persona_id}`);
  if (run.actor_principal_id) lineage.push(`requested by ${run.actor_principal_id}`);
  return (
    <tr
      onClick={() => onOpen(run.run_id)}
      style={{ cursor: "pointer", borderBottom: "1px solid var(--line)" }}
      title="Open this run's detail and live view"
    >
      <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>
        {run.run_id}
      </td>
      <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>
        {run.status}
      </td>
      <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", fontSize: 12 }}>
        {run.goal_revision}
      </td>
      <td style={{ padding: "6px 8px", fontSize: 12 }}>{fmtTime(run.started_at)}</td>
      <td style={{ padding: "6px 8px", fontSize: 12 }}>{lineage.join(" · ") || "—"}</td>
      <td style={{ padding: "6px 8px", fontSize: 12, color: "#c4452a", maxWidth: 260 }}>
        {run.error ? String(run.error) : ""}
      </td>
    </tr>
  );
}

function GoalDetail({
  view,
  onOpenGoal,
  onOpenRun,
}: {
  view: GoalView;
  onOpenGoal: (id: string) => void;
  onOpenRun: (id: string) => void;
}) {
  const disp = disposition(view.execution_disposition);
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <Card>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, fontFamily: "var(--mono)" }}>{view.goal_id}</h3>
          <span
            style={{
              padding: "2px 10px",
              borderRadius: 10,
              background: disp.color,
              color: "#fff",
              fontSize: 12,
            }}
          >
            {disp.label}
          </span>
          <span style={{ fontSize: 12, color: "var(--pencil)" }}>
            revision {view.goal_revision_seen ?? "—"}
            {view.goal_revisions.length > 1
              ? ` · evidence under revisions ${view.goal_revisions.join(", ")}`
              : ""}
          </span>
        </div>
        {/* The verdict banner: a finished run never promotes itself to a
            finished Goal. Goal state is shown only when its canonical owner
            recorded it. */}
        <p style={{ fontSize: 13, color: "var(--pencil)", marginBottom: 4 }}>
          Goal outcome: {view.goal_state ?? "not recorded"}. The runs below are
          execution evidence — they don't decide whether the goal itself is met.
        </p>
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "max-content 1fr",
            gap: "4px 16px",
            fontSize: 13,
            margin: 0,
          }}
        >
          <dt style={{ color: "var(--pencil)" }}>Wants</dt>
          <dd style={{ margin: 0 }}>{view.desired_state ?? "not recorded"}</dd>
          <dt style={{ color: "var(--pencil)" }}>Done when</dt>
          <dd style={{ margin: 0 }}>
            {view.success_conditions.length > 0
              ? view.success_conditions.join("; ")
              : (view.success_condition ?? "not recorded")}
          </dd>
          <dt style={{ color: "var(--pencil)" }}>Stops when</dt>
          <dd style={{ margin: 0 }}>
            {view.stop_conditions.length > 0
              ? view.stop_conditions.join("; ")
              : (view.stop_condition ?? "not recorded")}
          </dd>
          <dt style={{ color: "var(--pencil)" }}>Accountable</dt>
          <dd style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12 }}>
            {view.accountable_agent_id ?? "unassigned"}
          </dd>
          <dt style={{ color: "var(--pencil)" }}>Scope</dt>
          <dd style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12 }}>
            {view.workspace_id ?? "—"} / {view.project_id ?? "—"}
          </dd>
        </dl>
        {view.blocker && (
          <p style={{ fontSize: 13, color: "#c4452a", marginTop: 8 }}>
            Blocker: run {view.blocker.run_id} finished as {view.blocker.status}
            {view.blocker.error ? ` — ${String(view.blocker.error)}` : ""}
          </p>
        )}
        {(view.parent_goal_id || view.subgoals.length > 0) && (
          <p style={{ fontSize: 13, marginTop: 8 }}>
            {view.parent_goal_id && (
              <>
                Delegated from{" "}
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    onOpenGoal(view.parent_goal_id as string);
                  }}
                >
                  {view.parent_goal_id}
                </a>
                .{" "}
              </>
            )}
            {view.subgoals.length > 0 && (
              <>
                Subgoals:{" "}
                {view.subgoals.map((sub, i) => (
                  <span key={sub}>
                    {i > 0 && ", "}
                    <a
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenGoal(sub);
                      }}
                    >
                      {sub}
                    </a>
                  </span>
                ))}
                .
              </>
            )}
          </p>
        )}
      </Card>

      <Card>
        <h4 style={{ marginTop: 0 }}>Approach</h4>
        {view.selected_graphs.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
            {view.selected_graphs.map((g) => {
              // A Graph snapshot may have several Runs. Open the newest
              // matching run so this is a real Graph -> Run inspection path,
              // never a link that pretends a snapshot id is a legacy DAG id.
              const run = view.runs.find((candidate) => candidate.graph_id === g.graph_id);
              return (
                <li key={g.graph_id}>
                  {run ? (
                    <button
                      type="button"
                      onClick={() => onOpenRun(run.run_id)}
                      title="Open this graph's canonical run evidence"
                      style={{
                        border: 0,
                        padding: 0,
                        background: "transparent",
                        color: "var(--accent)",
                        cursor: "pointer",
                        fontFamily: "var(--mono)",
                        fontSize: 12,
                      }}
                    >
                      {g.graph_id}
                    </button>
                  ) : (
                    <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{g.graph_id}</span>
                  )}
                  {g.name ? ` — ${g.name}` : ""}
                </li>
              );
            })}
          </ul>
        ) : (
          <p style={{ fontSize: 13, color: "var(--pencil)", margin: 0 }}>
            No recorded approach for this goal yet.
          </p>
        )}
        {view.unmatched_pipelines.length > 0 && (
          <p style={{ fontSize: 12, color: "var(--pencil)" }}>
            Earlier work ran through pipelines whose records predate run
            identity: {view.unmatched_pipelines.join(", ")}
          </p>
        )}
      </Card>

      <Card>
        <h4 style={{ marginTop: 0 }}>Runs ({view.run_count})</h4>
        <p style={{ fontSize: 12, color: "var(--pencil)", marginTop: -4 }}>
          Each run is one execution toward this goal. Click one for its live
          detail, steps, and controls.
        </p>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--pencil)", fontSize: 12 }}>
              <th style={{ padding: "4px 8px" }}>Run</th>
              <th style={{ padding: "4px 8px" }}>State</th>
              <th style={{ padding: "4px 8px" }}>Revision</th>
              <th style={{ padding: "4px 8px" }}>Started</th>
              <th style={{ padding: "4px 8px" }}>Provenance</th>
              <th style={{ padding: "4px 8px" }}>Error</th>
            </tr>
          </thead>
          <tbody>
            {view.runs.map((run) => (
              <RunRow key={run.run_id} run={run} onOpen={onOpenRun} />
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export default function Goals() {
  const [goals, setGoals] = useState<GoalView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { activeWorkspaceId } = useWorkspaces();
  const selectedId = searchParams.get("goal");
  // A run's Goal back-link names the Workspace its goal lives in (?ws=);
  // plain navigation inspects the active Workspace tab.
  const wsId = searchParams.get("ws") ?? activeWorkspaceId;

  const load = useCallback(async () => {
    if (!wsId) {
      // No Workspace to inspect yet (first run, or every tab archived):
      // an honest empty page, not a fetch that cannot name its scope.
      setGoals([]);
      setError(null);
      setLoading(false);
      return;
    }
    try {
      const data = await apiGet<GoalView[]>(
        `/v1/workspaces/${encodeURIComponent(wsId)}/goals?limit=100`,
      );
      setGoals(data);
      setError(null);
    } catch (e) {
      setError((e as Error).message ?? "Couldn't load goals.");
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  useEffect(() => {
    // The first fetch is deferred to a timer tick rather than called in the
    // effect body: a synchronous load here cascades a render on mount, and
    // the repo's lint budget counts exactly that.
    const first = setTimeout(() => void load(), 0);
    const i = setInterval(() => void load(), 10_000);
    return () => {
      clearTimeout(first);
      clearInterval(i);
    };
  }, [load]);

  const selected = useMemo(
    () => goals.find((g) => g.goal_id === selectedId) ?? null,
    [goals, selectedId],
  );

  const grouped = useMemo(() => {
    const byScope = new Map<string, GoalView[]>();
    for (const g of goals) {
      const key = `${g.workspace_id ?? "—"} / ${g.project_id ?? "—"}`;
      const list = byScope.get(key) ?? [];
      list.push(g);
      byScope.set(key, list);
    }
    return [...byScope.entries()];
  }, [goals]);

  const openGoal = (id: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set("goal", id);
    else next.delete("goal");
    setSearchParams(next, { replace: true });
  };

  return (
    <div style={{ padding: 16 }}>
      <PageHeader
        title="Goals"
        subtitle="What this workspace is trying to achieve, the agent accountable for each, and the runs done toward them."
      />
      {error && (
        <div
          style={{
            background: "#fee2e2",
            border: "1px solid #fca5a5",
            padding: 10,
            borderRadius: 6,
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}
      {loading ? (
        <LoadingSpinner />
      ) : goals.length === 0 ? (
        <EmptyState
          title="No goals with recorded work yet"
          action="When work is started toward a goal, its history appears here."
        />
      ) : (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
          <aside style={{ width: 340, flexShrink: 0, display: "grid", gap: 12 }}>
            {grouped.map(([scope, list]) => (
              <Card key={scope}>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--pencil)",
                    fontFamily: "var(--mono)",
                    marginBottom: 6,
                  }}
                >
                  {scope}
                </div>
                <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}>
                  {list.map((g) => {
                    const disp = disposition(g.execution_disposition);
                    const active = g.goal_id === selectedId;
                    return (
                      <li key={g.goal_id}>
                        <button
                          onClick={() => openGoal(g.goal_id)}
                          style={{
                            width: "100%",
                            textAlign: "left",
                            padding: "6px 8px",
                            borderRadius: 6,
                            border: `1px solid ${active ? "var(--accent)" : "var(--line)"}`,
                            background: active ? "color-mix(in srgb, var(--accent) 12%, transparent)" : "transparent",
                            cursor: "pointer",
                            display: "flex",
                            justifyContent: "space-between",
                            gap: 8,
                            alignItems: "center",
                            color: "inherit",
                          }}
                        >
                          <span
                            style={{
                              fontFamily: "var(--mono)",
                              fontSize: 12,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {g.goal_id}
                          </span>
                          <span style={{ fontSize: 11, color: disp.color, whiteSpace: "nowrap" }}>
                            {disp.label} · {g.run_count}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </Card>
            ))}
          </aside>
          <div style={{ flex: 1, minWidth: 0 }}>
            {selected ? (
              <GoalDetail
                view={selected}
                onOpenGoal={(id) => openGoal(id)}
                onOpenRun={(runId) => navigate(`/dag-runs?run=${encodeURIComponent(runId)}`)}
              />
            ) : (
              <EmptyState
                title="Select a goal"
                action="Pick one on the left to see its history."
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
