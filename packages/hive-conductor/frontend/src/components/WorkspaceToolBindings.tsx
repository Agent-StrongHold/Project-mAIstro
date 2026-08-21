import { useEffect, useState } from "react";
import { apiGet, apiPut } from "../lib/api";
import { useUser } from "../App";
import { useWorkspaces, type WorkspaceRole } from "../context/WorkspaceContext";

type PersonaAgentOption = {
  agent_id: string;
  role: string;
  default_tools: string[];
  default_skills: string[];
};

type AgentBindingDraft = {
  checkedDefaults: Set<string>;
  extraTools: string;
  promptFragment: string;
};

function myRole(
  members: { user_id: string; role: WorkspaceRole }[],
  userId: string | undefined,
): WorkspaceRole | null {
  return members.find((m) => m.user_id === userId)?.role ?? null;
}

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Per-workspace tool-binding settings screen -- consumes services/
 * tool_binding.py's resolve_agent_tools()/resolve_agent_prompt_fragment()
 * (Phase E), which had no UI to write from until now. Owner-only, same
 * toggle-panel shape as WorkspaceShare. Each agent's declared default tools
 * are checkboxes; anything typed into "additional tools" is layered on top,
 * so a workspace can both narrow (uncheck a default) and extend (add a
 * tool the persona never declared) what one agent may call here. */
export function WorkspaceToolBindings() {
  const user = useUser();
  const { activeWorkspace, refresh } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<PersonaAgentOption[]>([]);
  const [drafts, setDrafts] = useState<Record<string, AgentBindingDraft>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workspaceId = activeWorkspace?.id;
  const personaId = activeWorkspace?.persona_template_id;

  useEffect(() => {
    if (!open || !personaId || !workspaceId) return;
    let cancelled = false;
    (async () => {
      try {
        const options = await apiGet<PersonaAgentOption[]>(
          `/v1/workspaces/persona-templates/${personaId}/agents`,
        );
        if (cancelled) return;
        setAgents(options);
        setDrafts((prevDrafts) => {
          const next: Record<string, AgentBindingDraft> = {};
          for (const agent of options) {
            if (prevDrafts[agent.agent_id]) {
              next[agent.agent_id] = prevDrafts[agent.agent_id];
              continue;
            }
            const binding = activeWorkspace?.tool_bindings.find(
              (b) => b.agent_id === agent.agent_id,
            );
            const tools = binding ? binding.tools : agent.default_tools;
            next[agent.agent_id] = {
              checkedDefaults: new Set(agent.default_tools.filter((t) => tools.includes(t))),
              extraTools: tools.filter((t) => !agent.default_tools.includes(t)).join(", "),
              promptFragment: binding?.prompt_fragment ?? "",
            };
          }
          return next;
        });
      } catch {
        setAgents([]);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Re-key off ids, not the whole activeWorkspace object (which gets a new
    // identity on every refresh()), so opening the panel doesn't refetch on
    // every unrelated poll -- only when it opens or the workspace changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, personaId, workspaceId]);

  if (!activeWorkspace) return null;
  const role = myRole(activeWorkspace.members, user?.id);
  if (role !== "owner") return null;

  function toggleDefault(agentId: string, tool: string) {
    setDrafts((prev) => {
      const draft = prev[agentId];
      if (!draft) return prev;
      const checkedDefaults = new Set(draft.checkedDefaults);
      if (checkedDefaults.has(tool)) {
        checkedDefaults.delete(tool);
      } else {
        checkedDefaults.add(tool);
      }
      return { ...prev, [agentId]: { ...draft, checkedDefaults } };
    });
  }

  function setExtraTools(agentId: string, value: string) {
    setDrafts((prev) => {
      const draft = prev[agentId];
      if (!draft) return prev;
      return { ...prev, [agentId]: { ...draft, extraTools: value } };
    });
  }

  function setPromptFragment(agentId: string, value: string) {
    setDrafts((prev) => {
      const draft = prev[agentId];
      if (!draft) return prev;
      return { ...prev, [agentId]: { ...draft, promptFragment: value } };
    });
  }

  async function handleSave() {
    if (!workspaceId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const bindings = agents.map((agent) => {
        const draft = drafts[agent.agent_id];
        const checked = draft ? Array.from(draft.checkedDefaults) : agent.default_tools;
        const extra = draft ? parseCommaList(draft.extraTools) : [];
        return {
          agent_id: agent.agent_id,
          tools: Array.from(new Set([...checked, ...extra])),
          prompt_fragment: draft?.promptFragment ?? "",
        };
      });
      await apiPut(`/v1/workspaces/${workspaceId}/tool-bindings`, { bindings });
      await refresh();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save tool bindings");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace-tool-bindings">
      <button
        type="button"
        className="workspace-tab workspace-tool-bindings-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        Tools
      </button>
      {open && (
        <div className="workspace-tool-bindings-panel">
          <div className="workspace-tool-bindings-title">
            {activeWorkspace.name} tool bindings
          </div>
          {agents.length === 0 && (
            <div className="workspace-tool-bindings-empty">
              This persona declares no agents to configure.
            </div>
          )}
          {agents.map((agent) => {
            const draft = drafts[agent.agent_id];
            return (
              <div key={agent.agent_id} className="workspace-tool-bindings-agent">
                <div className="workspace-tool-bindings-agent-name">
                  {agent.agent_id}
                  {agent.role && (
                    <span className="workspace-tool-bindings-agent-role"> — {agent.role}</span>
                  )}
                </div>
                {agent.default_tools.length > 0 && (
                  <div className="workspace-tool-bindings-defaults">
                    {agent.default_tools.map((tool) => (
                      <label key={tool}>
                        <input
                          type="checkbox"
                          checked={draft?.checkedDefaults.has(tool) ?? true}
                          onChange={() => toggleDefault(agent.agent_id, tool)}
                        />
                        {tool}
                      </label>
                    ))}
                  </div>
                )}
                <input
                  value={draft?.extraTools ?? ""}
                  onChange={(e) => setExtraTools(agent.agent_id, e.target.value)}
                  placeholder="Additional tools (comma-separated)"
                  aria-label={`Additional tools for ${agent.agent_id}`}
                />
                <textarea
                  value={draft?.promptFragment ?? ""}
                  onChange={(e) => setPromptFragment(agent.agent_id, e.target.value)}
                  placeholder="Extra prompt guidance for this agent, in this workspace"
                  aria-label={`Prompt fragment for ${agent.agent_id}`}
                />
              </div>
            );
          })}
          {error && <div className="workspace-tool-bindings-error">{error}</div>}
          <button type="button" disabled={busy} onClick={() => void handleSave()}>
            Save
          </button>
        </div>
      )}
    </div>
  );
}
