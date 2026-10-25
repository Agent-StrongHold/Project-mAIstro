/** Named aliases of the generated API contract; no handwritten response shapes. */
import type { components } from "./types.gen";

export type Schedule = components["schemas"]["Schedule"];
export type MCPServer = components["schemas"]["MCPServer"];
export type MCPTool = components["schemas"]["MCPTool"];

/** One audit-trail row: GET /v1/audit (#358). */
export type AuditEntry = components["schemas"]["AuditEntry"];
/** One bounded audit page; `next_cursor` is null at the end of the walk. */
export type AuditPage = components["schemas"]["AuditPage"];
/** The deployment's stated audit read-surface bounds (GET /v1/audit/retention). */
export type AuditRetention = components["schemas"]["AuditRetention"];
/** Severity union as the backend spells it on every audit row. */
export type AuditSeverity = components["schemas"]["AuditEntry"]["severity"];
