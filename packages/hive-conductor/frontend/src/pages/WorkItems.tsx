import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { WorkItemDraftModal, type WorkItemDraft } from "../components/WorkItemDraftModal";
import { apiGet } from "../lib/api";
import { labelForWorkType, type WorkItemType } from "../lib/pmCapabilities";
import { LoadingSpinner, PageHeader, useToast } from "../components/shared";

type DraftRow = WorkItemDraft;

export default function WorkItems() {
  const toast = useToast();
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [createType, setCreateType] = useState<WorkItemType | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGet<{ drafts: DraftRow[] }>("/v1/work-items");
      setDrafts(res.drafts ?? []);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load drafts", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const statusColor = (s: string) => {
    if (s === "posted") return "var(--ok, #5a9a4a)";
    if (s === "ready") return "var(--accent)";
    if (s === "cancelled") return "var(--pencil)";
    return "var(--pencil)";
  };

  return (
    <div style={{ padding: "20px 24px", maxWidth: 900, margin: "0 auto" }}>
      <PageHeader
        title="Jira drafts"
        subtitle="Gated Jira hierarchy — clarify, edit, then confirm to post (never auto-created)"
        actions={
          <Link to="/agents" className="btn" style={{ fontSize: 9, padding: "2px 8px" }}>
            ← Program
          </Link>
        }
      />

      <div className="card" style={{ marginBottom: 14, padding: 12 }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 8 }}>
          CREATE NEW (requires your approval)
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(["initiative", "epic", "user_story", "dev_task", "subtask"] as WorkItemType[]).map((wt) => (
            <button
              key={wt}
              type="button"
              className="btn btn-accent"
              style={{ fontSize: 8 }}
              onClick={() => setCreateType(wt)}
            >
              + {labelForWorkType(wt)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : drafts.length === 0 ? (
        <div className="card" style={{ padding: 20, fontFamily: "var(--hand)", color: "var(--pencil)" }}>
          No drafts yet. Start from the Program page (suggestions or agent buttons) or create one above.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {drafts.map((d) => (
            <button
              key={d.id}
              type="button"
              className="card"
              style={{ textAlign: "left", padding: 12, cursor: "pointer" }}
              onClick={() => setOpenId(d.id)}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>
                  {labelForWorkType(d.work_type)}
                  {d.fields.summary ? `: ${d.fields.summary}` : ""}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: statusColor(d.status) }}>
                  {d.status}
                  {d.posted_issue_key ? ` · ${d.posted_issue_key}` : ""}
                </span>
              </div>
              {d.suggestion_reason && (
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 4 }}>
                  {d.suggestion_reason}
                </div>
              )}
            </button>
          ))}
        </div>
      )}

      {openId && (
        <WorkItemDraftModal
          draftId={openId}
          onClose={() => {
            setOpenId(null);
            void load();
          }}
          onPosted={() => void load()}
        />
      )}
      {createType && (
        <WorkItemDraftModal
          workType={createType}
          reason={`New ${labelForWorkType(createType)}`}
          onClose={() => {
            setCreateType(null);
            void load();
          }}
          onPosted={() => void load()}
        />
      )}
    </div>
  );
}
