import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AccountBanner } from "../components/AccountBanner";
import { AgentFleetCard, type FleetAgent } from "../components/AgentFleetCard";
import { DailyReport } from "../components/DailyReport";
import { SetupChecklist } from "../components/SetupChecklist";
import { WorkItemDraftModal } from "../components/WorkItemDraftModal";
import { apiGet, apiPost } from "../lib/api";
import { debugLog } from "../lib/debug";
import {
  isGatedCapability,
  labelForWorkType,
  workTypeForCapability,
  type WorkItemType,
} from "../lib/pmCapabilities";
import { usePmPoc } from "../context/PocMode";
import { useWorkspaces } from "../context/WorkspaceContext";
import { PM_NAV_DRAFTS, PM_PRODUCT_TAGLINE } from "../lib/pmBranding";
import { LoadingSpinner, PageHeader, useToast } from "../components/shared";

type InterviewState = {
  complete: boolean;
  step: number;
  total_steps: number;
  agent?: string;
  question?: string;
  message?: string;
};

type ProgramContext = {
  program_name: string;
  summary: string;
  goals: string[];
  tools: string[];
  facts: string[];
  interview_complete: boolean;
};

type ProgramResponse = {
  context: ProgramContext;
  interview: InterviewState;
};

type WorkItemSuggestion = {
  work_type: WorkItemType;
  label: string;
  reason: string;
  draft_id?: string | null;
};

type PulseResponse = {
  queued: { task_id: string; agent_id: string; capability: string; reason?: string }[];
  proposed?: { capability: string; reason: string; autonomous?: boolean }[];
  work_item_suggestions?: WorkItemSuggestion[];
};

type DraftModalState =
  | { mode: "closed" }
  | { mode: "open"; draftId?: string; workType?: WorkItemType; reason?: string; hint?: string };

export default function Fleet() {
  const pmPoc = usePmPoc();
  const { activeWorkspaceId } = useWorkspaces();
  const toast = useToast();
  const [agents, setAgents] = useState<FleetAgent[]>([]);
  const [program, setProgram] = useState<ProgramResponse | null>(null);
  const [suggestions, setSuggestions] = useState<WorkItemSuggestion[]>([]);
  const [lastPulse, setLastPulse] = useState<PulseResponse | null>(null);
  const [loading, setLoading] = useState(true);
  // Permanently null, and honestly so: `handleInvoke` either opens the gated
  // draft modal or does a full-page `window.location.href` navigation, so there
  // is no async window to show a busy state in. AgentFleetCard implements
  // `invoking` (disables the button, shows "Running…") and will light up on its
  // own if invocation ever becomes an in-page request.
  const [invokingId] = useState<string | null>(null);
  const [interviewAnswer, setInterviewAnswer] = useState("");
  const [guidance, setGuidance] = useState("");
  const [submittingInterview, setSubmittingInterview] = useState(false);
  const [pulsing, setPulsing] = useState(false);
  const [draftModal, setDraftModal] = useState<DraftModalState>({ mode: "closed" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Persona/Workspace system: scope the interview to the active tab so
      // two workspaces (even two of the same persona) track independent
      // progress, instead of sharing the one legacy global interview.
      const contextPath = activeWorkspaceId
        ? `/v1/program/context?workspace_id=${encodeURIComponent(activeWorkspaceId)}`
        : "/v1/program/context";
      const [agentData, progData] = await Promise.all([
        apiGet<FleetAgent[]>("/v1/agents"),
        apiGet<ProgramResponse>(contextPath),
      ]);
      setAgents(agentData);
      setProgram(progData);
      debugLog("fleet", "loaded", { agents: agentData.length, interview: progData.interview });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load fleet", "error");
    } finally {
      setLoading(false);
    }
  }, [toast, activeWorkspaceId]);

  const runPulse = useCallback(async () => {
    if (!program?.interview.complete) return;
    setPulsing(true);
    try {
      const res = await apiPost<PulseResponse>("/v1/program/pulse", { max_actions: 3 });
      setLastPulse(res);
      if (res.work_item_suggestions?.length) {
        setSuggestions(res.work_item_suggestions);
      }
      debugLog("fleet", "pulse", res);
      const n = res.queued?.length ?? 0;
      const s = res.work_item_suggestions?.length ?? 0;
      if (n || s) {
        toast(
          `Pulse: ${n} autonomous task(s) queued${s ? `, ${s} Jira suggestion(s)` : ""}`,
          "ok",
        );
      } else {
        toast("Fleet pulse complete (nothing new to queue)", "ok");
      }
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Pulse failed", "error");
    } finally {
      setPulsing(false);
    }
  }, [program, load, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitInterviewAnswer() {
    if (!interviewAnswer.trim()) return;
    setSubmittingInterview(true);
    try {
      const answerPath = activeWorkspaceId
        ? `/v1/program/interview/answer?workspace_id=${encodeURIComponent(activeWorkspaceId)}`
        : "/v1/program/interview/answer";
      const res = await apiPost<ProgramResponse & { queued_tasks?: { task_id: string }[] }>(
        answerPath,
        { answer: interviewAnswer.trim() },
      );
      setInterviewAnswer("");
      setProgram({ context: res.context, interview: res.interview });
      if (res.queued_tasks?.length) {
        toast(`Interview saved — fleet started ${res.queued_tasks.length} task(s)`, "ok");
      } else {
        toast("Saved — one step closer", "ok");
      }
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not save answer", "error");
    } finally {
      setSubmittingInterview(false);
    }
  }

  async function submitGuidance() {
    if (!guidance.trim()) return;
    try {
      const res = await apiPost<{ queued_tasks?: { task_id: string }[] }>("/v1/program/guidance", {
        text: guidance.trim(),
      });
      setGuidance("");
      if (res.queued_tasks?.length) {
        toast(`Guidance applied — ${res.queued_tasks.length} new task(s) queued`, "ok");
      } else {
        toast("Guidance recorded — fleet will use this context", "ok");
      }
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Guidance failed", "error");
    }
  }

  const handleInvoke = async (agentId: string, capability: string) => {
    if (isGatedCapability(capability)) {
      openGatedDraft(agentId, capability);
      return;
    }
    // Navigate to chat with the capability as a pre-filled prompt
    const label = capability.replace(/_/g, " ");
    window.location.href = `/chat?q=${encodeURIComponent(label)}`;
  };

  function openGatedDraft(_agentId: string, capability: string, reason?: string) {
    const workType = workTypeForCapability(capability);
    if (!workType) {
      toast("This action requires Jira approval but has no draft flow yet", "error");
      return;
    }
    const ctx = program?.context;
    setDraftModal({
      mode: "open",
      workType,
      reason: reason ?? `Create ${labelForWorkType(workType)} from fleet`,
      hint: ctx?.program_name ?? "",
    });
  }

  function openSuggestion(s: WorkItemSuggestion) {
    setDraftModal({
      mode: "open",
      draftId: s.draft_id ?? undefined,
      workType: s.work_type,
      reason: s.reason,
      hint: program?.context.program_name ?? "",
    });
  }

  const interview = program?.interview;
  const ctx = program?.context;

  return (
    <div style={{ padding: "20px 24px", maxWidth: 1100, margin: "0 auto" }}>
      <PageHeader
        title="Program Hyperagent"
        subtitle={PM_PRODUCT_TAGLINE}
        actions={
          <div style={{ display: "flex", gap: 6 }}>
            {pmPoc && interview?.complete && (
              <Link to="/work-items" className="btn" style={{ fontSize: 9, padding: "2px 8px" }}>
                {PM_NAV_DRAFTS}
              </Link>
            )}
            {interview?.complete && (
              <button
                type="button"
                className="btn"
                disabled={pulsing}
                onClick={() => void runPulse()}
                style={{ fontSize: 9, padding: "2px 8px" }}
              >
                {pulsing ? "Pulsing…" : "Fleet pulse"}
              </button>
            )}
            <Link to="/missions" className="btn" style={{ fontSize: 9, padding: "2px 8px" }}>
              Missions
            </Link>
          </div>
        }
      />

      <AccountBanner />
      <SetupChecklist />
      <DailyReport />

      {loading ? (
        <LoadingSpinner />
      ) : (
        <>
          {interview && !interview.complete && interview.question && (
            <div
              className="card"
              style={{ marginBottom: 20, borderLeft: "4px solid var(--accent)", padding: 16 }}
            >
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 6 }}>
                INTAKE INTERVIEW · step {interview.step}/{interview.total_steps}
                {interview.agent ? ` · ${interview.agent}` : ""}
              </div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, marginBottom: 12 }}>{interview.question}</div>
              <textarea
                className="input-field"
                rows={3}
                value={interviewAnswer}
                onChange={(e) => setInterviewAnswer(e.target.value)}
                placeholder="Your answer…"
                style={{ width: "100%", marginBottom: 8 }}
              />
              <button
                type="button"
                className="btn btn-accent"
                disabled={submittingInterview || !interviewAnswer.trim()}
                onClick={() => void submitInterviewAnswer()}
              >
                {submittingInterview ? "Saving…" : "Continue interview"}
              </button>
            </div>
          )}

          {interview?.complete && ctx && (
            <div className="card" style={{ marginBottom: 20, padding: 14 }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 8 }}>
                PROGRAM CONTEXT (learned)
              </div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 20, fontWeight: 600 }}>{ctx.program_name || "Your program"}</div>
              {ctx.summary && (
                <div style={{ fontFamily: "var(--hand)", fontSize: 13, color: "var(--pencil)", marginTop: 4 }}>{ctx.summary}</div>
              )}
              {ctx.goals.length > 0 && (
                <div style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 10 }}>
                  <strong>Goals:</strong> {ctx.goals.join(" · ")}
                </div>
              )}
              <div style={{ marginTop: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
                <input
                  className="input-field"
                  style={{ flex: 1, minWidth: 200 }}
                  value={guidance}
                  onChange={(e) => setGuidance(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void submitGuidance()}
                  placeholder="Teach the fleet something new…"
                />
                <button type="button" className="btn btn-accent" disabled={!guidance.trim()} onClick={() => void submitGuidance()}>
                  Send guidance
                </button>
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 8 }}>
                Guidance queues autonomous work only (poll Jira, scan risks, etc.). Jira creates stay in the draft flow below.
              </div>
            </div>
          )}

          {interview?.complete && (suggestions.length > 0 || lastPulse?.proposed?.length) && (
            <div className="card" style={{ marginBottom: 20, padding: 14 }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 10 }}>
                LAST PULSE
              </div>
              {lastPulse?.proposed && lastPulse.proposed.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 8, marginBottom: 6 }}>Autonomous (ran or queued)</div>
                  <ul style={{ margin: 0, paddingLeft: 18, fontFamily: "var(--mono)", fontSize: 9 }}>
                    {lastPulse.proposed.map((p, i) => (
                      <li key={i}>
                        {p.capability}: {p.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {suggestions.length > 0 && (
                <div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 8, marginBottom: 6 }}>
                    Suggested Jira items (review before post)
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {suggestions.map((s) => (
                      <button
                        key={`${s.work_type}-${s.reason.slice(0, 24)}`}
                        type="button"
                        className="btn"
                        style={{ textAlign: "left", fontSize: 9 }}
                        onClick={() => openSuggestion(s)}
                      >
                        {s.label}: {s.reason}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {interview?.complete && (
            <div style={{ marginBottom: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {(["initiative", "epic", "user_story", "dev_task", "subtask"] as WorkItemType[]).map((wt) => (
                <button
                  key={wt}
                  type="button"
                  className="btn"
                  style={{ fontSize: 8 }}
                  onClick={() =>
                    setDraftModal({
                      mode: "open",
                      workType: wt,
                      reason: `Manual ${labelForWorkType(wt)}`,
                      hint: ctx?.program_name ?? "",
                    })
                  }
                >
                  + {labelForWorkType(wt)}
                </button>
              ))}
            </div>
          )}

          <div className="card" style={{ marginBottom: 14, padding: 10, fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)" }}>
            <strong style={{ color: "var(--ink)" }}>Autonomous</strong> — poll Jira, Airtable, scan risks, web research (fleet pulse).
            {" "}
            <strong style={{ color: "var(--ink)" }}>Gated</strong> — dashed tags; initiative → epic → story → task → subtask via{" "}
            <Link to="/work-items" style={{ color: "var(--accent)" }}>{PM_NAV_DRAFTS}</Link>.
          </div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 10 }}>
            SIX-AGENT FLEET · Intake, Program Manager, Delivery, Risk, Reporting, Research
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 16,
            }}
          >
            {agents.map((agent) => (
              <AgentFleetCard
                key={agent.id}
                agent={agent}
                invoking={invokingId === agent.id}
                onInvoke={handleInvoke}
                onGatedInvoke={openGatedDraft}
                disabled={!interview?.complete}
              />
            ))}
          </div>
          {!interview?.complete && (
            <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 12 }}>
              Complete the interview above before the fleet runs autonomously.
            </div>
          )}
        </>
      )}

      {draftModal.mode === "open" && (
        <WorkItemDraftModal
          draftId={draftModal.draftId ?? null}
          workType={draftModal.workType}
          reason={draftModal.reason}
          hint={draftModal.hint}
          onClose={() => setDraftModal({ mode: "closed" })}
          onPosted={() => void load()}
        />
      )}
    </div>
  );
}
