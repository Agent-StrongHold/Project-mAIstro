// Workspace Attention (#1049) — projection over HITL pauses + failed Runs.
//
// Settling a HITL pause posts to the canonical answer door named by
// `answer_href` (same authority as CLI). Failed Runs only offer inspection.
// Defer/dismiss persistence and Messages/Optimizer MERGE remain later slices.

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet } from "../lib/api";
import type { AttentionItem, AttentionPayload } from "../lib/attention";
import {
  attentionClassLabel,
  attentionPath,
  inspectionHref,
  parseHitlAnswerHref,
  submitHitlAnswer,
} from "../lib/attention";
import { useWorkspaces } from "../context/WorkspaceContext";
import { Card, EmptyState, Hex, LoadingSpinner, PageHeader } from "../components/shared";

function classVariant(name: string): "ok" | "danger" | "warn" | "muted" | "accent" | "" {
  if (name === "time_sensitive" || name === "severity") return "danger";
  if (name === "blocking") return "warn";
  if (name === "queued") return "accent";
  return "muted";
}

function AttentionRow({
  item,
  onInspect,
  onAnswered,
}: {
  item: AttentionItem;
  onInspect: (href: string) => void;
  onAnswered: () => void;
}) {
  const door = parseHitlAnswerHref(item.answer_href);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!door || !answer.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitHitlAnswer(door.runId, door.nodeId, answer.trim());
      setAnswer("");
      onAnswered();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't submit answer.");
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
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
        <Hex variant={classVariant(item.attention_class)}>
          {attentionClassLabel(item.attention_class)}
        </Hex>
        <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>
          #{item.rank} · {item.source_kind}
        </span>
      </div>
      <p style={{ margin: 0, fontSize: 14 }}>{item.reason}</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button type="button" onClick={() => onInspect(inspectionHref(item))}>
          Open run
        </button>
      </div>
      {door ? (
        <div
          style={{ display: "grid", gap: 6, marginTop: 4 }}
          data-testid={`attention-answer-${item.rank}`}
        >
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
            <button type="button" disabled={busy || !answer.trim()} onClick={() => void submit()}>
              {busy ? "Submitting…" : "Submit answer"}
            </button>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>
              {door.path}
            </span>
          </div>
          {error ? (
            <p style={{ margin: 0, color: "#c4452a", fontSize: 12 }} role="alert">
              {error}
            </p>
          ) : null}
        </div>
      ) : (
        <span style={{ fontSize: 12, color: "var(--pencil)" }}>
          No answer door (deadline passed or non-HITL)
        </span>
      )}
    </li>
  );
}

export default function Attention() {
  const { activeWorkspaceId, ready: workspacesReady } = useWorkspaces();
  const navigate = useNavigate();
  const [payload, setPayload] = useState<AttentionPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!activeWorkspaceId) {
      setPayload(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await apiGet<AttentionPayload>(attentionPath(activeWorkspaceId));
      setPayload(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load Attention.");
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (!workspacesReady) return;
    const first = setTimeout(() => void load(), 0);
    return () => clearTimeout(first);
  }, [load, workspacesReady]);

  const summary = payload?.summary;
  const items = payload?.items ?? [];

  return (
    <div style={{ padding: 16 }} data-testid="workspace-attention">
      <PageHeader
        title="Attention"
        subtitle="What needs you in this Workspace — ranked from canonical HITL pauses and failed Runs. Answers post to the same HITL door as CLI."
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
              {summary?.truncated ? (
                <Hex variant="warn">Truncated</Hex>
              ) : null}
              {summary?.hitl_unavailable ? (
                <Hex variant="warn" data-testid="attention-hitl-unavailable">
                  HITL pauses unavailable
                </Hex>
              ) : null}
              {summary && summary.rising.length > 0 ? (
                <span style={{ fontSize: 12, color: "var(--pencil)" }}>
                  Rising: {summary.rising.length}
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
                  onInspect={(href) => navigate(href)}
                  onAnswered={() => void load()}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
