// Goal inspection contract types (#65) — the shapes
// GET /v1/workspaces/{workspaceId}/goals serves.
//
// These are the Workspace-centric inspection view's response contract, not
// page-local UI state, so they live in src/lib/ beside the other cross-surface
// response shapes (the same home pmCapabilities and rumSchema use). The page
// imports them; a second surface reading the same door imports the same
// spelling instead of re-declaring a local copy the typed-client ratchet
// would have to bank as new debt.

export type AttemptEvidence = {
  attempt_id: string;
  ordinal: number;
  status: string;
  runtime_id: string;
  executor_id: string;
  error: string | null;
  cancellation_cause: string | null;
};

export type NodeRunEvidence = {
  node_run_id: string;
  node_id: string;
  ordinal: number;
  status: string;
  error: string | null;
  attempts: AttemptEvidence[];
};

export type ArtifactEvidence = {
  artifact_id: string;
  request_id: string;
  status: string;
  attempt_count: number;
  node_run_ids: string[];
};

export type RunEvidence = {
  run_id: string;
  canonical_run_id: string;
  status: string;
  goal_revision: string;
  dag_id: string;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
  parent_run_id: string | null;
  parent_node_run_id: string | null;
  actor_principal_id: string | null;
  persona_id: string | null;
  graph_id: string | null;
  graph_name: string | null;
  provenance: Record<string, unknown>;
};

export type GoalView = {
  goal_id: string;
  workspace_id: string | null;
  project_id: string | null;
  goal_state: string | null;
  goal_state_source: string;
  goal_revision_seen: string | null;
  goal_revisions: string[];
  accountable_agent_id: string | null;
  desired_state: string | null;
  success_condition: string | null;
  stop_condition: string | null;
  success_conditions: string[];
  stop_conditions: string[];
  parent_goal_id: string | null;
  execution_disposition: string;
  blocker: { run_id: string; status: string; error: string | null } | null;
  selected_graphs: { graph_id: string; name: string | null }[];
  unmatched_pipelines: string[];
  subgoals: string[];
  run_count: number;
  runs: RunEvidence[];
};
