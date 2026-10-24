/**
 * Workspace product preferences on the canonical profile (#1050).
 *
 * Stored under `preferences.*` so UI, PATCH /v1/profile, and chat
 * `profile_set` share one durable owner. Fresh accounts with no preference
 * land on Workspace Home with balanced restore aggressiveness.
 */

export const LANDING_PREF_KEY = "workspace_default_landing";
export const RESTORE_PREF_KEY = "workspace_restore_aggressiveness";

/** Surfaces a user may pin as their Workspace default. Home is the baseline. */
export const LANDING_OPTIONS: { path: string; label: string }[] = [
  { path: "/home", label: "Workspace Home" },
  { path: "/chat", label: "Chat" },
  { path: "/goals", label: "Goals" },
  { path: "/backlog", label: "Backlog" },
  { path: "/work-items", label: "Work items" },
];

const ALLOWED_LANDING = new Set(LANDING_OPTIONS.map((o) => o.path));

export const DEFAULT_LANDING_PATH = "/home";

/** How eagerly to restore a prior surface after absence (#1822 consumes). */
export const RESTORE_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: "off", label: "Off", hint: "Always open the default landing — never restore." },
  { value: "brief", label: "Brief", hint: "Restore only after a short absence." },
  {
    value: "balanced",
    label: "Balanced",
    hint: "Default — absolute window plus prior-session proportion.",
  },
  {
    value: "generous",
    label: "Generous",
    hint: "Hold sessions longer; restore after longer absences.",
  },
];

const ALLOWED_RESTORE = new Set(RESTORE_OPTIONS.map((o) => o.value));

export const DEFAULT_RESTORE_VALUE = "balanced";

/** Normalize a stored preference into a safe in-app path, or the Home baseline. */
export function resolveLandingPath(raw: unknown): string {
  if (typeof raw !== "string") return DEFAULT_LANDING_PATH;
  const path = raw.trim();
  if (!path.startsWith("/") || path.includes("//") || path.includes("..")) {
    return DEFAULT_LANDING_PATH;
  }
  // Strip query/hash — landing is a surface identity, not a deep-link bag.
  const bare = path.split(/[?#]/, 1)[0] ?? DEFAULT_LANDING_PATH;
  if (!ALLOWED_LANDING.has(bare)) return DEFAULT_LANDING_PATH;
  return bare;
}

export function resolveRestoreAggressiveness(raw: unknown): string {
  if (typeof raw !== "string") return DEFAULT_RESTORE_VALUE;
  const value = raw.trim().toLowerCase();
  if (!ALLOWED_RESTORE.has(value)) return DEFAULT_RESTORE_VALUE;
  return value;
}

export function landingLabel(path: string): string {
  return LANDING_OPTIONS.find((o) => o.path === path)?.label ?? "Workspace Home";
}

export function restoreLabel(value: string): string {
  return RESTORE_OPTIONS.find((o) => o.value === value)?.label ?? "Balanced";
}
