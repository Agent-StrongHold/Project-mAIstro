/** Workspace Attention wire shapes (#1049). Under `lib/` for typed-client ratchet. */

import { ApiError } from "./api";

export type AttentionItem = {
  source_kind: string;
  source_id: string;
  workspace_id: string;
  attention_class: string;
  /** Issue interruption vocabulary: blocking | popup | queued | waiting. */
  interruption?: string;
  rank: number;
  reason: string;
  evidence: Record<string, unknown>;
  answer_href: string | null;
};

export type AttentionWaitingQuality = {
  count: number;
  valuable_source_ids: string[];
};

export type AttentionSummary = {
  counts_by_class: Record<string, number>;
  counts_by_interruption?: Record<string, number>;
  highest_class: string | null;
  rising: string[];
  waiting_quality?: AttentionWaitingQuality;
  truncated: boolean;
  /** True when the canonical graph spine cannot supply HITL pauses. */
  hitl_unavailable?: boolean;
  /** How many scanned items were hidden by defer/dismiss preferences. */
  dismissed_count?: number;
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
  // MessageBoard / OptimizationInbox MERGEd into Attention — stay here.
  if (item.source_kind === "agent_message" || item.source_kind === "optimizer_proposal") {
    return "/attention";
  }
  return "/dag-runs";
}

/** Decide a pending optimizer proposal through its canonical owner (#1049). */
export async function decideOptimizerProposal(
  proposalId: string,
  decision: "accept" | "reject",
): Promise<unknown> {
  const path = `/v1/optimizer/proposals/${encodeURIComponent(proposalId)}/${decision}`;
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: "{}",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(detail || `Couldn't ${decision} proposal`, response.status, path);
  }
  if (response.status === 204) return undefined;
  return response.json();
}

/** Parse a canonical HITL answer door (`/v1/hitl/{run}/{node}/answer`). */
export function parseHitlAnswerHref(
  href: string | null,
): { runId: string; nodeId: string; path: string } | null {
  if (!href || typeof href !== "string") return null;
  const bare = href.trim().split(/[?#]/, 1)[0] ?? "";
  const m = /^\/v1\/hitl\/([^/]+)\/([^/]+)\/answer$/.exec(bare);
  if (!m) return null;
  const runId = decodeURIComponent(m[1] ?? "");
  const nodeId = decodeURIComponent(m[2] ?? "");
  if (!runId || !nodeId) return null;
  return { runId, nodeId, path: bare };
}

/** Defer or dismiss one Attention source for this Workspace (#1049). */
export async function dismissAttentionItem(
  workspaceId: string,
  sourceKind: string,
  sourceId: string,
  action: "dismiss" | "defer" = "dismiss",
): Promise<unknown> {
  const response = await fetch(
    `/v1/workspaces/${workspaceId}/attention/dismiss`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ sourceKind, sourceId, action }),
    },
  );
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(
      detail || "Couldn't dismiss Attention item",
      response.status,
      `/v1/workspaces/${workspaceId}/attention/dismiss`,
    );
  }
  return response.json();
}

/** Pause reasons whose durable store requires a nonempty ``verdict`` field. */
const VERDICT_PAUSE_REASONS = new Set([
  "awaiting_human_approval",
  "awaiting_human_review",
  "awaiting_role_delegate",
]);

/**
 * Build the HITL answer body from Attention evidence (#1049).
 * Question pauses take `{ answer }`; approve/review/delegate take `{ verdict }`
 * so a text-only "approved" cannot leave the Run paused on a malformed shape.
 */
export function hitlAnswerBody(
  pausedReason: unknown,
  text: string,
): Record<string, string> {
  const trimmed = text.trim();
  const reason = typeof pausedReason === "string" ? pausedReason : "";
  if (VERDICT_PAUSE_REASONS.has(reason)) {
    const lower = trimmed.toLowerCase();
    const verdict =
      lower === "approve" || lower === "approved" || lower === "yes"
        ? "approved"
        : lower === "reject" || lower === "rejected" || lower === "no" || lower === "deny"
          ? "rejected"
          : trimmed;
    return { verdict };
  }
  return { answer: trimmed };
}

/** Post an answer through the canonical HITL door (#1049 Attention CTA). */
export async function submitHitlAnswer(
  runId: string,
  nodeId: string,
  body: Record<string, string>,
): Promise<unknown> {
  // Bare `fetch` + literal path: shipped-surface-truth discovers mutating
  // browser calls by scanning fetch sites, not apiPost helpers.
  const response = await fetch(`/v1/hitl/${runId}/${nodeId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(detail || "HITL answer failed", response.status, "/v1/hitl/.../answer");
  }
  if (response.status === 204) return undefined;
  return response.json();
}

const CLASS_LABELS: Record<string, string> = {
  severity: "Severity",
  time_sensitive: "Time-sensitive",
  blocking: "Blocking",
  queued: "Queued",
  follow_up: "Follow-up",
  proactive: "Proactive",
};

const INTERRUPTION_LABELS: Record<string, string> = {
  blocking: "Blocking",
  popup: "Popup",
  queued: "Queued",
  waiting: "Waiting",
};

export function attentionClassLabel(name: string): string {
  return CLASS_LABELS[name] ?? name;
}

export function interruptionLabel(name: string): string {
  return INTERRUPTION_LABELS[name] ?? name;
}
