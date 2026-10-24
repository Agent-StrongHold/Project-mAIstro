/** Workspace Attention wire shapes (#1049). Under `lib/` for typed-client ratchet. */

export type AttentionItem = {
  source_kind: string;
  source_id: string;
  workspace_id: string;
  attention_class: string;
  rank: number;
  reason: string;
  evidence: Record<string, unknown>;
  answer_href: string | null;
};

export type AttentionSummary = {
  counts_by_class: Record<string, number>;
  highest_class: string | null;
  rising: string[];
  truncated: boolean;
};

export type AttentionPayload = {
  workspace_id: string;
  items: AttentionItem[];
  summary: AttentionSummary;
};

export function attentionPath(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/attention`;
}

/** Open the owning full surface for an Attention item (not the HITL API URL). */
export function inspectionHref(item: AttentionItem): string {
  if (item.source_kind === "failed_run") {
    return `/dag-runs?run=${encodeURIComponent(item.source_id)}`;
  }
  if (item.source_kind === "hitl_node_run") {
    const runId = item.source_id.split("/")[0] || item.source_id;
    return `/dag-runs?run=${encodeURIComponent(runId)}`;
  }
  return "/dag-runs";
}

const CLASS_LABELS: Record<string, string> = {
  severity: "Severity",
  time_sensitive: "Time-sensitive",
  blocking: "Blocking",
  queued: "Queued",
  follow_up: "Follow-up",
  proactive: "Proactive",
};

export function attentionClassLabel(name: string): string {
  return CLASS_LABELS[name] ?? name;
}
