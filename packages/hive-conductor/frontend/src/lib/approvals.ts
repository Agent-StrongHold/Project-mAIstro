/** Approvals / HITL wire shapes (#2278). Under `lib/` for typed-client. */

export type CapabilityApproval = {
  request_id: string;
  action: string;
  params: Record<string, unknown>;
  tier: string;
  requester: string;
  rationale: string;
};

export type CapabilityApprovalsList = {
  pending: CapabilityApproval[];
};

export type PendingHitlWork = {
  run_id: string;
  node_id: string;
  project_id: string;
  payload: Record<string, unknown>;
  paused_at: string | null;
};

export const CAPABILITY_APPROVALS_PATH = "/v1/capabilities/approvals";
export const HITL_PENDING_PATH = "/v1/hitl/pending";

export function capabilityApprovalPath(requestId: string): string {
  return `/v1/capabilities/approvals/${encodeURIComponent(requestId)}`;
}

export function hitlAnswerPath(runId: string, nodeId: string): string {
  return `/v1/hitl/${encodeURIComponent(runId)}/${encodeURIComponent(nodeId)}/answer`;
}

export function hitlCancelPath(runId: string, nodeId: string): string {
  return `/v1/hitl/${encodeURIComponent(runId)}/${encodeURIComponent(nodeId)}/cancel`;
}
