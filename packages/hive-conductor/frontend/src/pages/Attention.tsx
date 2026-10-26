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

function AttentionRow({
  item,
  workspaceId,
  onInspect,
  onAnswered,
}: {
  item: AttentionItem;
  workspaceId: string;
  onInspect: (href: string) => void;
  onAnswered: () => void;
}) {
  const door = parseHitlAnswerHref(item.answer_href);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pausedReason = item.evidence?.paused_reason;
  const needsVerdict =
    pausedReason === "awaiting_human_approval" ||
    pausedReason === "awaiting_human_review" ||
    pausedReason === "awaiting_role_delegate";
  const isOptimizer = item.source_kind === "optimizer_proposal";
  const isMessage = item.source_kind === "agent_message";
  const inspectLabel =
    isMessage || isOptimizer ? "Stay on Attention" : "Open run";

  const submit = async (text: string) => {
    if (!door || !text.trim() || busy) return;
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
    if (busy) return;
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
    if (!isOptimizer || busy) return;
    setBusy(true);
    setError(null);
    try {
      await decideOptimizerProposal(item.source_id, decision);
      onAnswered();
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
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button type="button" onClick={() => onInspect(inspectionHref(item))}>
          {inspectLabel}
        </button>
        <button
          type="button"
          disabled={busy}
          data-testid="attention-defer"
          onClick={() => void hide("defer")}
        >
          Defer
        </button>
        <button
          type="button"
          disabled={busy}
          data-testid="attention-dismiss"
          onClick={() => void hide("dismiss")}
        >
          Dismiss
        </button>
      </div>
      {isOptimizer ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} data-testid="attention-optimizer-decide">
          <button
            type="button"
            disabled={busy}
            data-testid="attention-optimizer-accept"
            onClick={() => void decideProposal("accept")}
          >
            {busy ? "Working…" : "Accept proposal"}
          </button>
          <button
            type="button"
            disabled={busy}
            data-testid="attention-optimizer-reject"
            onClick={() => void decideProposal("reject")}
          >
            Reject proposal
          </button>
        </div>
      ) : null}
      {door ? (
        <div
          style={{ display: "grid", gap: 6, marginTop: 4 }}
          data-testid={`attention-answer-${item.rank}`}
        >
          {needsVerdict ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button
                type="button"
                disabled={busy}
                data-testid="attention-approve"
                onClick={() => void submit("approved")}
              >
                {busy ? "Submitting…" : "Approve"}
              </button>
              <button
                type="button"
                disabled={busy}
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
                  disabled={busy}
                  aria-label={`Answer for ${item.source_id}`}
                  style={{ display: "block", width: "100%", marginTop: 4 }}
                />
              </label>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button
                  type="button"
                  disabled={busy || !answer.trim()}
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
