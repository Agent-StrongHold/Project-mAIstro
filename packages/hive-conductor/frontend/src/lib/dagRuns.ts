/** Canonical Run inspection/control client (#1036). Under `lib/` for typed-client. */

import { ApiError } from "./api";
import type { ArtifactEvidence, NodeRunEvidence } from "./goalInspection";

export type EventType = "pm_node_started" | "pm_node_completed" | "pm_node_failed";

export type DagEvent = {
  event_type: EventType;
  role: string;
  capability: string;
  payload: Record<string, unknown>;
  timestamp: number;
};

export type RunSummary = {
  id: string;
  user_id: string;
  started_at: number;
  finished_at: number | null;
  event_count: number;
  node_states: Record<string, string>;
};

export type RunDetail = RunSummary & {
  status?: string;
  canonical_run_id?: string;
  events: DagEvent[];
  node_runs?: NodeRunEvidence[];
  artifacts?: ArtifactEvidence[];
  workspace_id?: string | null;
  goal_context?: { goal_id: string; goal_revision: string };
};

const NONTERMINAL = new Set(["created", "queued", "running", "waiting", "paused"]);

export function runIsCancellable(status: string | null | undefined): boolean {
  if (!status) return false;
  return NONTERMINAL.has(status.trim().toLowerCase());
}

/** Cancel through `POST /v1/dag-runs/{id}/cancel` — delegates to canonical spine. */
export async function cancelDagRun(runId: string): Promise<{
  run_id: string;
  status: string;
  cancelled: boolean;
}> {
  const response = await fetch(`/v1/dag-runs/${runId}/cancel`, {
    method: "POST",
    credentials: "same-origin",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(detail || "Cancel failed", response.status, `/v1/dag-runs/${runId}/cancel`);
  }
  return (await response.json()) as {
    run_id: string;
    status: string;
    cancelled: boolean;
  };
}
