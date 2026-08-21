import { useCallback, useEffect, useState, type ReactNode } from "react";
import { apiGet, apiPatch, apiPost } from "../lib/api";
import { labelForWorkType, type WorkItemType } from "../lib/pmCapabilities";
import { useToast } from "./shared";

type ClarifyingQuestion = {
  id: string;
  question: string;
  answer: string;
  required: boolean;
};

type WorkItemFields = {
  summary: string;
  description: string;
  project_key: string;
  parent_key: string;
  priority: string;
  labels: string[];
  assignee: string;
  due_date: string;
};

export type WorkItemDraft = {
  id: string;
  work_type: WorkItemType;
  status: string;
  suggestion_reason: string;
  clarifying_questions: ClarifyingQuestion[];
  fields: WorkItemFields;
  jira_preview: Record<string, unknown>;
  posted_issue_key?: string | null;
};

type Props = {
  draftId?: string | null;
  workType?: WorkItemType;
  reason?: string;
  hint?: string;
  onClose: () => void;
  onPosted?: (issueKey: string, taskId: string) => void;
};

export function WorkItemDraftModal({
  draftId: initialDraftId,
  workType,
  reason,
  hint,
  onClose,
  onPosted,
}: Props) {
  const toast = useToast();
  const [draft, setDraft] = useState<WorkItemDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState<"clarify" | "edit" | "review">("clarify");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [posting, setPosting] = useState(false);

  const loadDraft = useCallback(
    async (id: string) => {
      const res = await apiGet<{ draft: WorkItemDraft }>(`/v1/work-items/${id}`);
      setDraft(res.draft);
      const initial: Record<string, string> = {};
      for (const q of res.draft.clarifying_questions) {
        if (q.answer) initial[q.id] = q.answer;
      }
      setAnswers(initial);
      setStep(res.draft.status === "ready" || res.draft.status === "posted" ? "edit" : "clarify");
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        if (initialDraftId) {
          await loadDraft(initialDraftId);
        } else if (workType) {
          const res = await apiPost<{ draft: WorkItemDraft }>("/v1/work-items/suggest", {
            work_type: workType,
            reason: reason ?? "",
            hint: hint ?? "",
          });
          if (!cancelled) {
            setDraft(res.draft);
            setStep("clarify");
          }
        }
      } catch (err) {
        if (!cancelled) {
          toast(err instanceof Error ? err.message : "Could not load draft", "error");
          onClose();
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialDraftId, workType, reason, hint, loadDraft, onClose, toast]);

  if (loading || !draft) {
    return (
      <ModalShell title="Jira work item" onClose={onClose}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, padding: 24 }}>Loading draft…</div>
      </ModalShell>
    );
  }

  const activeDraft = draft;
  const label = labelForWorkType(activeDraft.work_type);

  async function submitClarify() {
    setSaving(true);
    try {
      const res = await apiPost<{ draft: WorkItemDraft }>(`/v1/work-items/${activeDraft.id}/clarify`, {
        answers,
      });
      setDraft(res.draft);
      setStep(res.draft.status === "ready" ? "edit" : "clarify");
      if (res.draft.status === "ready") {
        toast("Ready to edit and post", "ok");
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not save answers", "error");
    } finally {
      setSaving(false);
    }
  }

  async function saveFields(updates: Partial<WorkItemFields>) {
    setSaving(true);
    try {
      const res = await apiPatch<{ draft: WorkItemDraft }>(`/v1/work-items/${activeDraft.id}`, updates);
      setDraft(res.draft);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not save fields", "error");
    } finally {
      setSaving(false);
    }
  }

  async function confirmPost() {
    setPosting(true);
    try {
      const res = await apiPost<{
        draft: WorkItemDraft;
        jira: { issue_key?: string };
        task_id: string;
        message: string;
      }>(`/v1/work-items/${activeDraft.id}/confirm`);
      setDraft(res.draft);
      toast(res.message, "ok");
      onPosted?.(res.jira?.issue_key ?? "", res.task_id);
      onClose();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Post failed", "error");
    } finally {
      setPosting(false);
    }
  }

  return (
    <ModalShell title={`${label} → Jira`} onClose={onClose}>
      <p style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", margin: "0 0 12px" }}>
        {activeDraft.suggestion_reason}
      </p>
      <div style={{ display: "flex", gap: 6, marginBottom: 14, fontFamily: "var(--mono)", fontSize: 8 }}>
        {(["clarify", "edit", "review"] as const).map((s, i) => (
          <span
            key={s}
            style={{
              padding: "2px 8px",
              borderRadius: 3,
              border: "1px solid var(--rule)",
              opacity: step === s ? 1 : 0.45,
            }}
          >
            {i + 1}. {s === "clarify" ? "Questions" : s === "edit" ? "Edit fields" : "Confirm"}
          </span>
        ))}
      </div>

      {step === "clarify" && (
        <div>
          {activeDraft.clarifying_questions.map((q) => (
            <div key={q.id} style={{ marginBottom: 10 }}>
              <label style={{ fontFamily: "var(--mono)", fontSize: 9, display: "block", marginBottom: 4 }}>
                {q.question}
                {q.required ? " *" : ""}
              </label>
              <input
                className="input-field"
                style={{ width: "100%" }}
                value={answers[q.id] ?? q.answer}
                onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
              />
            </div>
          ))}
          <button
            type="button"
            className="btn btn-accent"
            disabled={saving}
            onClick={() => void submitClarify()}
          >
            {saving ? "Saving…" : "Continue to edit"}
          </button>
        </div>
      )}

      {(step === "edit" || step === "review") && (
        <div>
          <FieldRow
            label="Summary"
            value={activeDraft.fields.summary}
            onChange={(v) => void saveFields({ summary: v })}
            disabled={saving}
          />
          <FieldRow
            label="Description"
            value={activeDraft.fields.description}
            multiline
            onChange={(v) => void saveFields({ description: v })}
            disabled={saving}
          />
          <FieldRow
            label="Project key"
            value={activeDraft.fields.project_key}
            onChange={(v) => void saveFields({ project_key: v })}
            disabled={saving}
          />
          {activeDraft.fields.parent_key !== undefined && (
            <FieldRow
              label="Parent issue key"
              value={activeDraft.fields.parent_key}
              onChange={(v) => void saveFields({ parent_key: v })}
              disabled={saving}
            />
          )}
          <FieldRow
            label="Priority"
            value={activeDraft.fields.priority}
            onChange={(v) => void saveFields({ priority: v })}
            disabled={saving}
          />
          <pre
            style={{
              fontFamily: "var(--mono)",
              fontSize: 8,
              background: "var(--paper-2, #f5f5f0)",
              padding: 10,
              borderRadius: 4,
              marginTop: 12,
              overflow: "auto",
            }}
          >
            {JSON.stringify(activeDraft.jira_preview, null, 2)}
          </pre>
          {activeDraft.status === "posted" ? (
            <div style={{ fontFamily: "var(--mono)", fontSize: 10, marginTop: 8 }}>
              Posted: {activeDraft.posted_issue_key}
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button type="button" className="btn" onClick={() => setStep("clarify")}>
                Back to questions
              </button>
              <button
                type="button"
                className="btn btn-accent"
                disabled={posting || activeDraft.status !== "ready" || !activeDraft.fields.summary.trim()}
                onClick={() => void confirmPost()}
              >
                {posting ? "Posting…" : `Confirm & post ${label} to Jira`}
              </button>
            </div>
          )}
          {activeDraft.status !== "ready" && (
            <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 8 }}>
              Answer required clarifying questions before posting.
            </div>
          )}
        </div>
      )}
    </ModalShell>
  );
}

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      role="dialog"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ maxWidth: 520, width: "100%", maxHeight: "90vh", overflow: "auto", padding: 20 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontFamily: "var(--hand)", fontSize: 20 }}>{title}</h2>
          <button type="button" className="btn" onClick={onClose} style={{ fontSize: 9 }}>
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FieldRow({
  label,
  value,
  onChange,
  multiline,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
  disabled?: boolean;
}) {
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontFamily: "var(--mono)", fontSize: 9, display: "block", marginBottom: 4 }}>
        {label}
      </label>
      {multiline ? (
        <textarea
          className="input-field"
          rows={4}
          style={{ width: "100%" }}
          value={local}
          disabled={disabled}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={() => onChange(local)}
        />
      ) : (
        <input
          className="input-field"
          style={{ width: "100%" }}
          value={local}
          disabled={disabled}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={() => onChange(local)}
        />
      )}
    </div>
  );
}
