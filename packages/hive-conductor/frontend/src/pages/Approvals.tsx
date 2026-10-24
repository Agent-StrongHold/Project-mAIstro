import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, apiGet, apiPost } from "../lib/api";
import type {
  CapabilityApproval,
  CapabilityApprovalsList,
  PendingHitlWork,
} from "../lib/approvals";
import {
  CAPABILITY_APPROVALS_PATH,
  HITL_PENDING_PATH,
  capabilityApprovalPath,
  hitlAnswerPath,
  hitlCancelPath,
} from "../lib/approvals";
import { EmptyState, LoadingSpinner, PageHeader, useToast } from "../components/shared";

/**
 * Minimal Workspace approvals projection (#2278 / Parity P-1).
 *
 * Lists and answers the same canonical capability inbox and HITL pending set
 * as `maistro approvals` / `/v1/hitl/*`. No parallel store.
 */
export default function ApprovalsPage() {
  const toast = useToast();
  const [caps, setCaps] = useState<CapabilityApproval[] | null>(null);
  const [hitl, setHitl] = useState<PendingHitlWork[] | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [hitlError, setHitlError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});

  const loadCaps = useCallback(async () => {
    setCapsError(null);
    try {
      const body = await apiGet<CapabilityApprovalsList>(CAPABILITY_APPROVALS_PATH);
      setCaps(body.pending ?? []);
    } catch (e) {
      setCaps([]);
      setCapsError(e instanceof ApiError ? e.message : "Couldn't load capability approvals.");
    }
  }, []);

  const loadHitl = useCallback(async () => {
    setHitlError(null);
    try {
      const body = await apiGet<PendingHitlWork[]>(HITL_PENDING_PATH);
      setHitl(Array.isArray(body) ? body : []);
    } catch (e) {
      setHitl([]);
      // 503 = spine unavailable — honest empty with reason, not a fake queue.
      setHitlError(e instanceof ApiError ? e.message : "Couldn't load HITL pending work.");
    }
  }, []);

  const refresh = useCallback(async () => {
    await Promise.all([loadCaps(), loadHitl()]);
  }, [loadCaps, loadHitl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function resolveCap(requestId: string, approved: boolean) {
    setBusy(requestId);
    try {
      await apiPost(capabilityApprovalPath(requestId), { approved });
      toast(approved ? "Approved" : "Denied", "ok");
      await loadCaps();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Resolve failed", "error");
    } finally {
      setBusy(null);
    }
  }

  async function answerHitl(item: PendingHitlWork) {
    const key = `${item.run_id}:${item.node_id}`;
    const raw = answerDrafts[key] ?? '{"decision":"approved"}';
    let body: Record<string, unknown>;
    try {
      body = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      toast("Answer must be valid JSON", "error");
      return;
    }
    setBusy(key);
    try {
      await apiPost(hitlAnswerPath(item.run_id, item.node_id), body);
      toast("Answer submitted", "ok");
      await loadHitl();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Answer failed", "error");
    } finally {
      setBusy(null);
    }
  }

  async function cancelHitl(item: PendingHitlWork) {
    const key = `${item.run_id}:${item.node_id}:cancel`;
    setBusy(key);
    try {
      await apiPost(hitlCancelPath(item.run_id, item.node_id), {});
      toast("Cancelled", "ok");
      await loadHitl();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Cancel failed", "error");
    } finally {
      setBusy(null);
    }
  }

  const loading = caps === null && hitl === null;

  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle="Pending capability inbox and HITL pauses — same authority as API and maistro approvals"
        actions={
          <button type="button" className="btn" onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />

      {loading ? <LoadingSpinner /> : null}

      <section aria-labelledby="cap-approvals-heading" style={{ marginBottom: 28 }}>
        <h2 id="cap-approvals-heading" style={{ fontFamily: "var(--hand)", fontSize: 18 }}>
          Capability inbox
        </h2>
        <p style={{ fontSize: 13, opacity: 0.75, marginTop: 4 }}>
          <code>GET/POST /v1/capabilities/approvals</code> — identical to{" "}
          <code>maistro approvals list|approve|deny</code>.
        </p>
        {capsError && (
          <p role="alert" style={{ color: "var(--danger, #c4452a)" }}>
            {capsError}
          </p>
        )}
        {caps !== null && caps.length === 0 && !capsError ? (
          <EmptyState icon="✓" title="No pending capability approvals" />
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 0", display: "flex", flexDirection: "column", gap: 10 }}>
            {(caps ?? []).map((req) => (
              <li key={req.request_id} className="card" style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div>
                    <strong>{req.action}</strong>{" "}
                    <span style={{ opacity: 0.7 }}>[{req.tier}]</span>
                    <div style={{ fontSize: 13, marginTop: 4 }}>
                      {req.request_id} · by {req.requester || "unknown"}
                    </div>
                    {req.rationale && (
                      <p style={{ fontSize: 13, margin: "6px 0 0", opacity: 0.85 }}>{req.rationale}</p>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      className="btn btn-accent"
                      disabled={busy === req.request_id}
                      onClick={() => void resolveCap(req.request_id, true)}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={busy === req.request_id}
                      onClick={() => void resolveCap(req.request_id, false)}
                    >
                      Deny
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="hitl-heading">
        <h2 id="hitl-heading" style={{ fontFamily: "var(--hand)", fontSize: 18 }}>
          HITL (paused Runs)
        </h2>
        <p style={{ fontSize: 13, opacity: 0.75, marginTop: 4 }}>
          <code>GET /v1/hitl/pending</code> and answer/cancel on the same Run/NodeRun — no second store.
        </p>
        {hitlError && (
          <p role="alert" style={{ color: "var(--danger, #c4452a)" }}>
            {hitlError}
          </p>
        )}
        {hitl !== null && hitl.length === 0 && !hitlError ? (
          <EmptyState icon="✓" title="No Runs waiting on a human" />
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 0", display: "flex", flexDirection: "column", gap: 10 }}>
            {(hitl ?? []).map((item) => {
              const key = `${item.run_id}:${item.node_id}`;
              return (
                <li key={key} className="card" style={{ padding: 14 }}>
                  <div style={{ fontSize: 14 }}>
                    <Link to={`/dag-runs?run=${encodeURIComponent(item.run_id)}`}>Run {item.run_id}</Link>
                    {" · "}
                    node <code>{item.node_id}</code>
                    {item.paused_at ? ` · paused ${item.paused_at}` : ""}
                  </div>
                  {Object.keys(item.payload).length > 0 && (
                    <pre
                      style={{
                        marginTop: 8,
                        fontSize: 12,
                        overflow: "auto",
                        maxHeight: 160,
                        background: "var(--paper-2, transparent)",
                        padding: 8,
                      }}
                    >
                      {JSON.stringify(item.payload, null, 2)}
                    </pre>
                  )}
                  <label style={{ display: "block", marginTop: 8, fontSize: 13 }}>
                    Answer JSON
                    <textarea
                      value={answerDrafts[key] ?? '{"decision":"approved"}'}
                      onChange={(e) => setAnswerDrafts((d) => ({ ...d, [key]: e.target.value }))}
                      rows={3}
                      style={{ width: "100%", marginTop: 4, fontFamily: "var(--mono, monospace)", fontSize: 12 }}
                      aria-label={`Answer for ${item.run_id} ${item.node_id}`}
                    />
                  </label>
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button
                      type="button"
                      className="btn btn-accent"
                      disabled={busy === key}
                      onClick={() => void answerHitl(item)}
                    >
                      Submit answer
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={busy === `${key}:cancel`}
                      onClick={() => void cancelHitl(item)}
                    >
                      Cancel pause
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
