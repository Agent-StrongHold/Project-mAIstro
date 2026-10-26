// Workspace Attention (#1049) — projection over HITL pauses, failed Runs,
// unread agent messages (ex-MessageBoard), and pending optimizer proposals
// (ex-OptimizationInbox). Settling a HITL pause posts to `answer_href`;
// optimizer accept/reject posts to the canonical proposal doors. Defer/dismiss
// is preference evidence only — never a second lifecycle store.

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet } from "../lib/api";
import type { AttentionItem, AttentionPayload } from "../lib/attention";
import {
  attentionClassLabel,
  attentionPath,
  decideOptimizerProposal,
  dismissAttentionItem,
  hitlAnswerBody,
  inspectionHref,
  interruptionLabel,
  parseHitlAnswerHref,
  submitHitlAnswer,
} from "../lib/attention";
import { useWorkspaces } from "../context/WorkspaceContext";
import { Card, EmptyState, Hex, LoadingSpinner, PageHeader } from "../components/shared";

function classVariant(name: string): "ok" | "danger" | "warn" | "muted" | "accent" | "" {
  if (name === "time_sensitive" || name === "severity") return "danger";
  if (name === "blocking" || name === "popup") return "warn";
  if (name === "queued") return "accent";
  return "muted";
}

type TopologyProposalEvidence = {
  from_value?: unknown;
  to_value?: unknown;
  expected_improvement?: unknown;
};

function topologyProposalOf(item: AttentionItem): TopologyProposalEvidence | null {
  const raw = item.evidence?.topology_proposal;
  if (!raw || typeof raw !== "object") return null;
  return raw as TopologyProposalEvidence;
}


/** Render the pause subject (question / draft / document) before HITL controls. */
function PausePayload({ evidence }: { evidence: Record<string, unknown> }) {
  const raw = evidence.payload;
  if (!raw || typeof raw !== "object") return null;
  const payload = raw as Record<string, unknown>;
  const title = typeof payload.title === "string" ? payload.title.trim() : "";
  const question =
    typeof payload.question === "string"
      ? payload.question
      : payload.question && typeof payload.question === "object"
        ? JSON.stringify(payload.question, null, 2)
        : "";
  const draft = typeof payload.draft === "string" ? payload.draft : "";
  const document = typeof payload.document === "string" ? payload.document : "";
  const context =
    typeof payload.context_markdown === "string" ? payload.context_markdown : "";
  const choices = Array.isArray(payload.choices)
    ? payload.choices.filter((c): c is string => typeof c === "string")
    : [];
  const body = question || draft || document;
  if (!title && !body && !context && choices.length === 0) return null;

  const label = question ? "Question" : draft ? "Draft" : document ? "Document" : "Pause payload";

  return (
    <div
      style={{
        margin: 0,
        fontSize: 12,
        color: "var(--pencil)",
        border: "1px solid var(--line)",
        padding: "6px 8px",
        display: "grid",
        gap: 4,
      }}
      data-testid="attention-pause-payload"
    >
      <strong style={{ color: "var(--ink)" }}>{label}</strong>
      {title ? <div style={{ fontFamily: "var(--mono)" }}>{title}</div> : null}
      {body ? (
        <pre
          style={{
            margin: 0,
            whiteSpace: "pre-wrap",
            fontFamily: "var(--mono)",
            fontSize: 12,
          }}
        >
          {body}
        </pre>
      ) : null}
      {context ? (
        <pre
          style={{
            margin: 0,
            whiteSpace: "pre-wrap",
            fontFamily: "var(--mono)",
            fontSize: 11,
            opacity: 0.85,
          }}
        >
          {context}
        </pre>
      ) : null}
      {choices.length > 0 ? (
        <div style={{ fontFamily: "var(--mono)" }}>Choices: {choices.join(" · ")}</div>
      ) : null}
    </div>
  );
}

function AttentionRow({
  item,
  workspaceId,
  mutationsEnabled,
  onInspect,
  onAnswered,
}: {
  item: AttentionItem;
  workspaceId: string;
  /** False when displayed items belong to a Workspace that is no longer active. */
  mutationsEnabled: boolean;
  onInspect: (href: string) => void;
  onAnswered: () => void;
}) {
  const door = parseHitlAnswerHref(item.answer_href);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applyOutcome, setApplyOutcome] = useState<string | null>(null);
  const [applyDetail, setApplyDetail] = useState<string | null>(null);
  const canMutate = mutationsEnabled && !busy;

  const pausedReason = item.evidence?.paused_reason;
  const needsVerdict =
    pausedReason === "awaiting_human_approval" ||
    pausedReason === "awaiting_human_review" ||
    pausedReason === "awaiting_role_delegate";
  const isOptimizer = item.source_kind === "optimizer_proposal";
  const isMessage = item.source_kind === "agent_message";
  const topology = isOptimizer ? topologyProposalOf(item) : null;
  const topologyImprovement =
    typeof topology?.expected_improvement === "string" ? topology.expected_improvement : "";
  const inspectLabel =
    isMessage || isOptimizer ? "Stay on Attention" : "Open run";

  const submit = async (text: string) => {
    if (!mutationsEnabled || !door || !text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitHitlAnswer(door.runId, door.nodeId, hitlAnswerBody(pausedReason, text));
      setAnswer("");
      onAnswered();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't submit answer.");
    } finally {
      setBusy(false);
    }
  };

  const hide = async (action: "dismiss" | "defer") => {
    if (!mutationsEnabled || busy) return;
    setBusy(true);
    setError(null);
    try {
      await dismissAttentionItem(workspaceId, item.source_kind, item.source_id, action);
      onAnswered();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't update Attention preference.");
    } finally {
      setBusy(false);
    }
  };

  const decideProposal = async (decision: "accept" | "reject") => {
    if (!mutationsEnabled || !isOptimizer || busy) return;
    setBusy(true);
    setError(null);
    setApplyOutcome(null);
    setApplyDetail(null);
    try {
      const result = await decideOptimizerProposal(item.source_id, decision);
      const body =
        result && typeof result === "object" ? (result as Record<string, unknown>) : {};
      const outcome =
        typeof body.apply_outcome === "string" ? body.apply_outcome : decision === "accept" ? "recorded" : "rejected";
      const detail = typeof body.apply_detail === "string" ? body.apply_detail : "";
      setApplyOutcome(outcome);
      setApplyDetail(detail || null);
      // Keep the row visible when accept did not fully apply so the operator
      // can see follow-up (manual edit / escalation) before the projection drops it.
      if (decision === "reject" || outcome === "applied") {
        onAnswered();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Couldn't ${decision} proposal.`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li
      style={{
        border: "1px solid var(--line)",
        padding: "10px 12px",
        display: "grid",
        gap: 6,
      }}
      data-testid={`attention-item-${item.rank}`}
      data-source-kind={item.source_kind}
      data-interruption={item.interruption ?? ""}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
        <Hex variant={classVariant(item.attention_class)}>
          {attentionClassLabel(item.attention_class)}
        </Hex>
        {item.interruption ? (
          <Hex variant={classVariant(item.interruption)}>
            {interruptionLabel(item.interruption)}
          </Hex>
        ) : null}
        <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>
          #{item.rank} · {item.source_kind}
        </span>
      </div>
      <p style={{ margin: 0, fontSize: 14 }}>{item.reason}</p>
      <PausePayload evidence={item.evidence ?? {}} />
      {isMessage && typeof item.evidence?.body === "string" && item.evidence.body ? (
        <p
          style={{
            margin: 0,
            fontSize: 12,
            color: "var(--pencil)",
            whiteSpace: "pre-wrap",
            fontFamily: "var(--mono)",
          }}
        >
          {item.evidence.body}
        </p>
      ) : null}
      {topology ? (
        <div
          style={{
            margin: 0,
            fontSize: 12,
            color: "var(--pencil)",
            fontFamily: "var(--mono)",
            border: "1px solid var(--line)",
            padding: "6px 8px",
          }}
          data-testid="attention-topology-proposal"
        >
          <strong style={{ color: "var(--ink)" }}>Topology mutation:</strong>{" "}
          {String(topology.from_value ?? "—")} → {String(topology.to_value ?? "—")}
          {topologyImprovement ? (
            <div style={{ marginTop: 4 }}>{topologyImprovement}</div>
          ) : null}
        </div>
      ) : null}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button type="button" onClick={() => onInspect(inspectionHref(item))}>
          {inspectLabel}
        </button>
        <button
          type="button"
          disabled={!canMutate}
          data-testid="attention-defer"
          onClick={() => void hide("defer")}
        >
          Defer
        </button>
        <button
          type="button"
          disabled={!canMutate}
          data-testid="attention-dismiss"
          onClick={() => void hide("dismiss")}
        >
          Dismiss
        </button>
      </div>
      {isOptimizer ? (
        <div style={{ display: "grid", gap: 6 }} data-testid="attention-optimizer-decide">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              disabled={!canMutate}
              data-testid="attention-optimizer-accept"
              onClick={() => void decideProposal("accept")}
            >
              {busy ? "Working…" : "Accept proposal"}
            </button>
            <button
              type="button"
              disabled={!canMutate}
              data-testid="attention-optimizer-reject"
              onClick={() => void decideProposal("reject")}
            >
              Reject proposal
            </button>
          </div>
          {applyOutcome ? (
            <div
              style={{
                fontSize: 12,
                color: applyOutcome === "applied" ? "var(--ink)" : "#c4452a",
                fontFamily: "var(--mono)",
                border: "1px solid var(--line)",
                padding: "6px 8px",
              }}
              data-testid="attention-optimizer-apply-outcome"
            >
              Apply outcome: {applyOutcome}
              {applyDetail ? <div style={{ marginTop: 4 }}>{applyDetail}</div> : null}
              {applyOutcome !== "applied" && applyOutcome !== "rejected" ? (
                <div style={{ marginTop: 4 }}>
                  Proposal remains listed until apply succeeds or you reject it.
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      {door ? (
        <div
          style={{ display: "grid", gap: 6, marginTop: 4 }}
          data-testid={`attention-answer-${item.rank}`}
        >
          {!mutationsEnabled ? (
            <span style={{ fontSize: 12, color: "var(--pencil)" }} data-testid="attention-stale-workspace">
              Workspace changed — answer controls disabled until Attention reloads.
            </span>
          ) : needsVerdict ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button
                type="button"
                disabled={!canMutate}
                data-testid="attention-approve"
                onClick={() => void submit("approved")}
              >
                {busy ? "Submitting…" : "Approve"}
              </button>
              <button
                type="button"
                disabled={!canMutate}
                data-testid="attention-reject"
                onClick={() => void submit("rejected")}
              >
                Reject
              </button>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>
                {door.path}
              </span>
            </div>
          ) : (
            <>
              <label style={{ fontSize: 12, color: "var(--pencil)" }}>
                Answer (same door as CLI / API)
                <input
                  type="text"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  disabled={!canMutate}
                  aria-label={`Answer for ${item.source_id}`}
                  style={{ display: "block", width: "100%", marginTop: 4 }}
                />
              </label>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button
                  type="button"
                  disabled={!canMutate || !answer.trim()}
                  onClick={() => void submit(answer)}
                >
                  {busy ? "Submitting…" : "Submit answer"}
                </button>
                <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>
                  {door.path}
                </span>
              </div>
            </>
          )}
        </div>
      ) : (
        <span style={{ fontSize: 12, color: "var(--pencil)" }}>
          {isOptimizer
            ? "Settle via Accept/Reject (canonical optimizer doors)"
            : isMessage
              ? "Defer/Dismiss hides this message preference for the Workspace"
              : "No answer door (deadline passed or non-HITL)"}
        </span>
      )}
      {error ? (
        <p style={{ margin: 0, color: "#c4452a", fontSize: 12 }} role="alert" data-testid="attention-item-error">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export default function Attention() {
  const { activeWorkspaceId, ready: workspacesReady } = useWorkspaces();
  const navigate = useNavigate();
  const [payload, setPayload] = useState<AttentionPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Drop in-flight loads (incl. post-answer/dismiss refresh) after Workspace switch.
  const loadGenerationRef = useRef(0);
  const activeWorkspaceIdRef = useRef(activeWorkspaceId);
  activeWorkspaceIdRef.current = activeWorkspaceId;

  const load = useCallback(async () => {
    const workspaceId = activeWorkspaceIdRef.current;
    const generation = ++loadGenerationRef.current;
    if (!workspaceId) {
      if (generation === loadGenerationRef.current) {
        setPayload(null);
        setError(null);
        setLoading(false);
      }
      return;
    }
    setLoading(true);
    try {
      const data = await apiGet<AttentionPayload>(attentionPath(workspaceId));
      if (
        generation !== loadGenerationRef.current ||
        activeWorkspaceIdRef.current !== workspaceId
      ) {
        return;
      }
      setPayload(data);
      setError(null);
    } catch (e) {
      if (
        generation !== loadGenerationRef.current ||
        activeWorkspaceIdRef.current !== workspaceId
      ) {
        return;
      }
      setError(e instanceof ApiError ? e.message : "Couldn't load Attention.");
      setPayload(null);
    } finally {
      if (
        generation === loadGenerationRef.current &&
        activeWorkspaceIdRef.current === workspaceId
      ) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!workspacesReady) return;
    const first = setTimeout(() => void load(), 0);
    return () => {
      clearTimeout(first);
      // Abandon in-flight loads (initial or post-mutation) for the prior Workspace.
      loadGenerationRef.current += 1;
    };
  }, [load, workspacesReady, activeWorkspaceId]);

  const summary = payload?.summary;
  const items = payload?.items ?? [];
  const waitingQuality = summary?.waiting_quality;
  const mutationsEnabled =
    Boolean(activeWorkspaceId) && payload?.workspace_id === activeWorkspaceId;

  return (
    <div style={{ padding: 16 }} data-testid="workspace-attention">
      <PageHeader
        title="Attention"
        subtitle="What needs you in this Workspace — ranked from HITL pauses, failed Runs, agent messages, and optimizer suggestions. Answers stay on each source's canonical door."
        helpHref="/docs#workspaces"
      />

      {!workspacesReady || loading ? (
        <div data-testid="attention-loading" aria-busy="true" aria-label="Loading Attention">
          <LoadingSpinner />
        </div>
      ) : !activeWorkspaceId ? (
        <EmptyState title="No Workspace selected" action="Open a Workspace tab to load Attention" />
      ) : error ? (
        <Card>
          <p style={{ margin: 0, color: "#c4452a" }} data-testid="attention-error">
            {error}
          </p>
          <button type="button" onClick={() => void load()} style={{ marginTop: 8 }}>
            Retry
          </button>
        </Card>
      ) : (
        <>
          <Card>
            <div
              style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "baseline" }}
              data-testid="attention-summary"
            >
              <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                Highest:{" "}
                {summary?.highest_class
                  ? attentionClassLabel(summary.highest_class)
                  : "none"}
              </span>
              {summary &&
                Object.entries(summary.counts_by_class).map(([name, count]) => (
                  <Hex key={name} variant={classVariant(name)}>
                    {attentionClassLabel(name)} {count}
                  </Hex>
                ))}
              {summary?.counts_by_interruption &&
                Object.entries(summary.counts_by_interruption).map(([name, count]) => (
                  <Hex key={`i-${name}`} variant={classVariant(name)}>
                    {interruptionLabel(name)} {count}
                  </Hex>
                ))}
              {summary?.truncated ? (
                <Hex variant="warn">Truncated</Hex>
              ) : null}
              {summary?.hitl_unavailable ? (
                <Hex variant="warn" data-testid="attention-hitl-unavailable">
                  HITL pauses unavailable
                </Hex>
              ) : null}
              {(summary?.dismissed_count ?? 0) > 0 ? (
                <span style={{ fontSize: 12, color: "var(--pencil)" }} data-testid="attention-dismissed-count">
                  Hidden by preference: {summary?.dismissed_count}
                </span>
              ) : null}
              {summary && summary.rising.length > 0 ? (
                <span style={{ fontSize: 12, color: "var(--pencil)" }}>
                  Rising: {summary.rising.length}
                </span>
              ) : null}
              {waitingQuality && waitingQuality.count > 0 ? (
                <span
                  style={{ fontSize: 12, color: "var(--pencil)" }}
                  data-testid="attention-waiting-quality"
                >
                  Waiting: {waitingQuality.count}
                  {waitingQuality.valuable_source_ids.length > 0
                    ? ` · ${waitingQuality.valuable_source_ids.length} valuable`
                    : ""}
                </span>
              ) : null}
            </div>
          </Card>

          {items.length === 0 ? (
            <EmptyState title="Nothing needs attention right now" />
          ) : (
            <ul
              style={{ listStyle: "none", margin: "12px 0 0", padding: 0, display: "grid", gap: 10 }}
              data-testid="attention-items"
            >
              {items.map((item) => (
                <AttentionRow
                  key={`${item.source_kind}:${item.source_id}`}
                  item={item}
                  workspaceId={activeWorkspaceId}
                  mutationsEnabled={mutationsEnabled}
                  onInspect={(href) => navigate(href)}
                  onAnswered={() => {
                    // Dismiss/answer may finish after a Workspace switch; do not
                    // refresh B with a mutation that began on A.
                    if (activeWorkspaceIdRef.current !== activeWorkspaceId) return;
                    void load();
                  }}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
