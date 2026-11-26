/** Workspace persona picker and tool-binding shapes (#336). Under `lib/`
 * for typed-client: these mirror the workspace API's persona-template and
 * tool-binding payloads rather than any single page's local state. */

/** One option of GET /v1/workspaces/persona-templates. */
export type PersonaTemplateOption = {
  id: string;
  display_name: string;
  tagline: string;
};

/** One agent option offered for tool binding. */
export type PersonaAgentOption = {
  agent_id: string;
  role: string;
  default_tools: string[];
  default_skills: string[];
};

/** A binding being edited: which of the persona's defaults stay checked,
 * plus the free-form extras, until `PUT /tool-bindings` saves them. */
export type AgentBindingDraft = {
  checkedDefaults: Set<string>;
  extraTools: string;
  promptFragment: string;
};
