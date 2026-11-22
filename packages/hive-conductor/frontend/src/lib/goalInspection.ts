// Goal inspection entities come from the backend's OpenAPI response schema.
import type { components } from "../api/types.gen";

export type RunEvidence = components["schemas"]["GoalRunEvidence"];
export type GoalView = components["schemas"]["GoalInspectionView"];

// The older Run-detail endpoint still has an unstructured response contract.

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
