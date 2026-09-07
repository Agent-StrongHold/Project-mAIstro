// Strict declarative widget schema — the browser half of the #314 boundary.
//
// This mirrors `backend/services/dashboard_safety.py`: widget configuration is
// data the renderer interprets, never a request description. Model-authored
// `widget_update` blocks and server-loaded layouts both pass through it before
// anything is applied, so no configuration can name a destination, method,
// header, or body — the only fetches widgets issue are to fixed same-origin
// capability routes built from these fields.
//
// Keep the field sets in sync with the backend module; the e2e specs assert
// both halves reject the same payload families.

const COMMON_FIELDS = new Set([
  "refresh_minutes",
  "theme",
  "display",
  "target",
  "variables",
  "display_options",
]);

const KPI_FIELDS = new Set(["field", "sub", "source"]);

const JIRA_FIELDS = new Set(["project", "status", "days", "assignee", "jql_extra", "jira_display"]);

const CUSTOM_FIELDS = new Set([
  "source",
  "table",
  "filter_formula",
  "max_records",
  "field",
  "group_by",
  "display_field",
  "metric",
  "period",
  "query",
  "breakdown",
  "records",
  "count",
  "sub",
  ...JIRA_FIELDS,
]);

/** Per-type declarative fields. Unknown types are treated as `custom`. */
export const WIDGET_CONFIG_CAPABILITIES: Record<string, Set<string>> = {
  kpi: new Set([...KPI_FIELDS, ...COMMON_FIELDS]),
  jira: new Set([...JIRA_FIELDS, ...CUSTOM_FIELDS, ...COMMON_FIELDS]),
  "agent-orbs": COMMON_FIELDS,
  invocations: COMMON_FIELDS,
  "cost-donut": COMMON_FIELDS,
  trace: COMMON_FIELDS,
  custom: new Set([...CUSTOM_FIELDS, ...COMMON_FIELDS]),
};

/** Generic request primitives are never widget fields. */
export const REQUEST_PRIMITIVE_KEYS = new Set([
  "endpoint",
  "method",
  "params",
  "headers",
  "body",
  "url",
  "credentials",
]);

const IDENTIFIER_FIELDS = new Set([
  "source",
  "table",
  "project",
  "field",
  "group_by",
  "display_field",
  "metric",
  "period",
  "status",
  "assignee",
  "jira_display",
  "display",
  "theme",
  "sub",
]);

const FREE_TEXT_FIELDS = new Set(["query", "filter_formula", "jql_extra"]);

const MAX_STRING_LENGTH = 2048;
const MAX_RECORD_ENTRIES = 500;
const MAX_VALUE_DEPTH = 8;

export const WIDGET_SIZES = ["1", "2", "3", "4", "5", "6"] as const;
export const WIDGET_ROWS = ["1", "2", "3", "4"] as const;
export type WidgetSize = (typeof WIDGET_SIZES)[number];

export interface SanitizedWidget {
  id: string;
  type: string;
  title: string;
  size: WidgetSize;
  rows?: string;
  config?: Record<string, unknown>;
}

function decoded(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function hasScheme(value: string): boolean {
  return value.split("/", 1)[0].includes(":");
}

function identifierSafe(value: string): boolean {
  for (const variant of [value, decoded(value)]) {
    if (variant.includes("//") || variant.includes("..") || hasScheme(variant)) return false;
  }
  return true;
}

function sanitizeString(field: string, value: string): string | undefined {
  if (IDENTIFIER_FIELDS.has(field) && !identifierSafe(value)) return undefined;
  if (FREE_TEXT_FIELDS.has(field) && decoded(value).includes("..")) return undefined;
  return value.slice(0, MAX_STRING_LENGTH);
}

function sanitizeValue(field: string, value: unknown, depth: number): unknown {
  if (depth > MAX_VALUE_DEPTH) return undefined;
  if (typeof value === "boolean" || typeof value === "number") return value;
  if (typeof value === "string") return sanitizeString(field, value);
  if (Array.isArray(value)) {
    const items = value
      .slice(0, MAX_RECORD_ENTRIES)
      .map((item) => sanitizeValue(field, item, depth + 1))
      .filter((item) => item !== undefined);
    return items.length > 0 ? items : undefined;
  }
  if (value && typeof value === "object") {
    const clean: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (key.length > MAX_STRING_LENGTH) continue;
      const itemClean = sanitizeValue(key, item, depth + 1);
      if (itemClean !== undefined) clean[key] = itemClean;
    }
    return Object.keys(clean).length > 0 ? clean : undefined;
  }
  return undefined;
}

/** The declarative subset of one widget config for its type. */
export function sanitizeWidgetConfig(
  widgetType: string | undefined,
  config: unknown,
): Record<string, unknown> {
  if (!config || typeof config !== "object" || Array.isArray(config)) return {};
  const allowed =
    (widgetType && WIDGET_CONFIG_CAPABILITIES[widgetType]) ||
    WIDGET_CONFIG_CAPABILITIES.custom;
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config as Record<string, unknown>)) {
    if (!allowed.has(key)) continue;
    const valueClean = sanitizeValue(key, value, 0);
    if (valueClean !== undefined) clean[key] = valueClean;
  }
  return clean;
}

/** Constrain a whole widget envelope (id/type/title/size/rows/config). */
export function sanitizeWidget(widget: unknown): SanitizedWidget | null {
  if (!widget || typeof widget !== "object") return null;
  const w = widget as Record<string, unknown>;
  const type = typeof w.type === "string" && w.type ? w.type : "custom";
  const title =
    typeof w.title === "string" && w.title.trim() ? w.title.slice(0, 120) : "Widget";
  const size = WIDGET_SIZES.includes(w.size as WidgetSize) ? (w.size as WidgetSize) : "1";
  const rows = WIDGET_ROWS.includes(w.rows as (typeof WIDGET_ROWS)[number])
    ? (w.rows as string)
    : undefined;
  return {
    id: typeof w.id === "string" && w.id ? w.id : `w-${Date.now()}`,
    type,
    title,
    size,
    ...(rows ? { rows } : {}),
    config: sanitizeWidgetConfig(type, w.config),
  };
}

/**
 * Model-authored `widget_update` changes for one widget: only envelope fields
 * the model may select survive, and any `config` is sanitized against the
 * resulting type. Returns null when nothing declarative survived — the update
 * is rejected rather than applied as a no-op shell.
 */
export function sanitizeWidgetChanges(
  currentType: string,
  changes: unknown,
): Partial<SanitizedWidget> | null {
  if (!changes || typeof changes !== "object" || Array.isArray(changes)) return null;
  const raw = changes as Record<string, unknown>;
  const type =
    typeof raw.type === "string" && raw.type && WIDGET_CONFIG_CAPABILITIES[raw.type]
      ? raw.type
      : currentType;

  const clean: Partial<SanitizedWidget> = {};
  if (typeof raw.title === "string" && raw.title.trim()) clean.title = raw.title.slice(0, 120);
  if (WIDGET_SIZES.includes(raw.size as WidgetSize)) clean.size = raw.size as WidgetSize;
  if (WIDGET_ROWS.includes(raw.rows as (typeof WIDGET_ROWS)[number])) {
    clean.rows = raw.rows as string;
  }
  if (raw.config !== undefined) {
    const config = sanitizeWidgetConfig(type, raw.config);
    // A config that sanitizes to nothing was not declarative — applying an
    // empty shell would blank the widget's working config, so the config
    // portion is rejected rather than emptied.
    if (Object.keys(config).length > 0) clean.config = config;
  }
  if (type !== currentType) clean.type = type;
  return Object.keys(clean).length > 0 ? clean : null;
}
