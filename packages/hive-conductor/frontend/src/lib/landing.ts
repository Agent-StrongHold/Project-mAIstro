/**
 * Workspace default-landing preference (#1050 first slice).
 *
 * Stored on the canonical user profile (`preferences.workspace_default_landing`)
 * so UI, PATCH /v1/profile, and chat `profile_set` share one durable owner.
 * Fresh accounts with no preference land on Workspace Home.
 */

export const LANDING_PREF_KEY = "workspace_default_landing";

/** Surfaces a user may pin as their Workspace default. Home is the baseline. */
export const LANDING_OPTIONS: { path: string; label: string }[] = [
  { path: "/home", label: "Workspace Home" },
  { path: "/chat", label: "Chat" },
  { path: "/goals", label: "Goals" },
  { path: "/backlog", label: "Backlog" },
  { path: "/work-items", label: "Work items" },
];

const ALLOWED = new Set(LANDING_OPTIONS.map((o) => o.path));

export const DEFAULT_LANDING_PATH = "/home";

/** Normalize a stored preference into a safe in-app path, or the Home baseline. */
export function resolveLandingPath(raw: unknown): string {
  if (typeof raw !== "string") return DEFAULT_LANDING_PATH;
  const path = raw.trim();
  if (!path.startsWith("/") || path.includes("//") || path.includes("..")) {
    return DEFAULT_LANDING_PATH;
  }
  // Strip query/hash — landing is a surface identity, not a deep-link bag.
  const bare = path.split(/[?#]/, 1)[0] ?? DEFAULT_LANDING_PATH;
  if (!ALLOWED.has(bare)) return DEFAULT_LANDING_PATH;
  return bare;
}

export function landingLabel(path: string): string {
  return LANDING_OPTIONS.find((o) => o.path === path)?.label ?? "Workspace Home";
}
