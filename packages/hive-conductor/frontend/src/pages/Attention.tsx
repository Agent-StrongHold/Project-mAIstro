// Workspace Attention (#1049) — read-only projection over HITL pauses + failed Runs.
//
// Settling an item stays on the canonical HITL answer route named by
// `answer_href` (API). This page lists ranked items, shows the backend
// summary (not client-invented importance), and opens Run inspection for
// the underlying resource. Defer/dismiss persistence and Messages/Optimizer
// MERGE are later slices.

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet } from "../lib/api";
import type { AttentionItem, AttentionPayload } from "../lib/attention";
import {
  attentionClassLabel,
  attentionPath,
  inspectionHref,
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
}: {
  item: AttentionItem;
  onInspect: (href: string) => void;
}) {
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
        {item.answer_href ? (
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>
            Answer via API: {item.answer_href}
          </span>
        ) : (
          <span style={{ fontSize: 12, color: "var(--pencil)" }}>No answer door (deadline passed or non-HITL)</span>
        )}
      </div>
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
        subtitle="What needs you in this Workspace — ranked from canonical HITL pauses and failed Runs. Answering stays on the HITL API; this page does not settle work."
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
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
