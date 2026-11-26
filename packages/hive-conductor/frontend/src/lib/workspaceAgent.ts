/** Workspace Agent persona wire shapes (#2277). Under `lib/` for typed-client. */

export type WorkspaceAgentPersona = {
  workspace_id: string;
  workspace_agent_id: string;
  persona_template_id: string;
  created_at: string;
};

/** Spawn agents declared by a Workspace persona template (picker options). */
export type PersonaAgentOption = {
  agent_id: string;
  role: string;
  default_tools: string[];
  default_skills: string[];
};

export function workspaceAgentPath(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent`;
}
