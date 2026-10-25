import { useEffect, useState } from "react";
import { ApiError, apiGet, apiPut } from "../lib/api";
import type { PersonaAgentOption, WorkspaceAgentPersona } from "../lib/workspaceAgent";
import { workspaceAgentPath } from "../lib/workspaceAgent";
import { useUser } from "../App";
import { useToast } from "./shared";
import { useWorkspaces, type WorkspaceRole } from "../context/WorkspaceContext";

function myRole(
  members: { user_id: string; role: WorkspaceRole }[],
  userId: string | undefined,
): WorkspaceRole | null {
  return members.find((m) => m.user_id === userId)?.role ?? null;
}

/**
 * Workspace Agent persona swap (#2277) — same durable row as
 * `PUT /v1/workspaces/{id}/agent` and the Agent tool
 * `set_workspace_agent_persona`. Distinct from WorkspaceTabs (Workspace
 * persona-template chrome / PersonaWizard authoring).
 */
export function WorkspaceAgentPersonaControl() {
  const user = useUser();
  const toast = useToast();
  const { activeWorkspace } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const [agent, setAgent] = useState<WorkspaceAgentPersona | null>(null);
  const [options, setOptions] = useState<PersonaAgentOption[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workspaceId = activeWorkspace?.id;
  const personaId = activeWorkspace?.persona_template_id;
  const role = myRole(activeWorkspace?.members ?? [], user?.id);
  const canEdit = role === "owner";

  useEffect(() => {
    if (!open || !workspaceId) return;
    let cancelled = false;
    (async () => {
      setError(null);
      try {
        const [current, agents] = await Promise.all([
          apiGet<WorkspaceAgentPersona>(workspaceAgentPath(workspaceId)),
          personaId
            ? apiGet<PersonaAgentOption[]>(
                `/v1/workspaces/persona-templates/${encodeURIComponent(personaId)}/agents`,
              )
            : Promise.resolve([] as PersonaAgentOption[]),
        ]);
        if (cancelled) return;
        setAgent(current);
        setDraft(current.persona_template_id);
        setOptions(agents);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Couldn't load Workspace Agent persona.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, workspaceId, personaId]);

  if (!workspaceId) return null;

  async function save() {
    if (!workspaceId || !canEdit || !draft || busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiPut<WorkspaceAgentPersona>(workspaceAgentPath(workspaceId), {
        persona_template_id: draft,
      });
      setAgent(updated);
      setDraft(updated.persona_template_id);
      toast("Workspace Agent persona updated", "ok");
      setOpen(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't swap Workspace Agent persona.");
    } finally {
      setBusy(false);
    }
  }

  const optionIds = new Set(options.map((o) => o.agent_id));
  if (agent && !optionIds.has(agent.persona_template_id)) {
    // Current value may be the default before any fleet spawn match.
    optionIds.add(agent.persona_template_id);
  }

  return (
    <div className="workspace-share">
      <button
        type="button"
        className="workspace-tab workspace-tool-bindings-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        Agent persona
      </button>
      {open && (
        <div className="workspace-share-panel" role="region" aria-label="Workspace Agent persona">
          <div className="workspace-share-title">
            Workspace Agent persona
            {agent && (
              <span className="workspace-share-role" title={agent.workspace_agent_id}>
                {agent.workspace_agent_id}
              </span>
            )}
          </div>
          <p style={{ margin: "0 0 8px", fontSize: 13, opacity: 0.8 }}>
            Swaps the hat on the stable Workspace Agent without changing its id. This is not the
            Workspace tab persona picker.
          </p>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
            Persona
            <select
              value={draft}
              disabled={!canEdit || busy || !agent}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Workspace Agent persona template"
            >
              {Array.from(optionIds).map((id) => {
                const opt = options.find((o) => o.agent_id === id);
                return (
                  <option key={id} value={id}>
                    {opt ? `${opt.agent_id}${opt.role ? ` — ${opt.role}` : ""}` : id}
                  </option>
                );
              })}
            </select>
          </label>
          {!canEdit && (
            <p role="status" style={{ fontSize: 13, marginTop: 8 }}>
              Only a Workspace owner can swap the Agent persona.
            </p>
          )}
          {error && (
            <div role="alert" className="workspace-tool-bindings-error">
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button type="button" disabled={!canEdit || busy || !draft || draft === agent?.persona_template_id} onClick={() => void save()}>
              {busy ? "Saving…" : "Save"}
            </button>
            <button type="button" disabled={busy} onClick={() => setOpen(false)}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
