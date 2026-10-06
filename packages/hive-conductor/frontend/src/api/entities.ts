/**
 * OpenAPI entity aliases for hive-conductor UI.
 * Import from here instead of re-declaring shapes in pages/ or components/.
 */
import type { components, paths } from "./types.gen";

type Schema = components["schemas"];

export type Agent = Schema["Agent"];
export type AuditEntry = Schema["AuditEntry"];
export type AuditSeverity = AuditEntry["severity"];
export type ChatSessionSummary = Schema["ChatSessionSummary"];
export type ElevateBody = Schema["ElevateBody"];
export type MCPServer = Schema["MCPServer"];
export type MCPTool = Schema["MCPTool"];
export type MemoryEntry = Schema["MemoryEntry"];
export type PatchSettingsBody = Schema["PatchSettingsBody"];
export type Schedule = Schema["Schedule"];
export type SettingsModel = Schema["SettingsModel"];
export type Skill = Schema["Skill"];

/** Normalized skill parameter row for UI tables. */
export type SkillParameter = {
  name: string;
  type: string;
  required: boolean;
};

export function skillParameters(skill: Skill): SkillParameter[] {
  return (skill.parameters ?? []).map((raw) => ({
    name: String(raw.name ?? ""),
    type: String(raw.type ?? "string"),
    required: Boolean(raw.required),
  }));
}

/** GET /v1/dashboard/demos item (OpenAPI returns unknown dicts). */
export type DashboardDemoSummary = {
  id: string;
  name: string;
  description: string;
  widget_count: number;
};

/** GET /v1/providers envelope (loosely typed in OpenAPI). */
export type LlmProviderRow = {
  name: string;
  label: string;
  models: string[];
  test_model: string;
  has_key: boolean;
  activated: boolean;
};

export type LlmProvidersResponse = {
  vault_available: boolean;
  providers: LlmProviderRow[];
};

export type WhoamiResponse = paths["/v1/auth/whoami"]["get"]["responses"][200]["content"]["application/json"];

/** Session user payload from GET /v1/auth/whoami (OpenAPI body is loosely typed). */
export type AuthenticatedUser = {
  id: string;
  username: string;
  role: string;
  session_policy?: {
    idle_timeout_seconds: number;
    absolute_ttl_seconds: number;
    effective_expires_at: string;
  };
};

export type SetupStatusResponse =
  paths["/v1/setup/status"]["get"]["responses"][200]["content"]["application/json"];

export type HealthResponse = paths["/health"]["get"]["responses"][200]["content"]["application/json"];
