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

/**
 * Absolute absence windows (ms) per aggressiveness band (#1050 / #1822).
 * Bands are policy knobs, not product law — proportional session length can
 * extend the balanced/generous windows further.
 */
export const RESTORE_ABSOLUTE_MS: Record<string, number> = {
  off: 0,
  brief: 15 * 60 * 1000,
  balanced: 4 * 60 * 60 * 1000,
  generous: 24 * 60 * 60 * 1000,
};

/** Surfaces recent-return may reopen (subset of product routes). */
export const RESTORE_SURFACES: ReadonlySet<string> = new Set([
  ...LANDING_OPTIONS.map((o) => o.path),
  "/attention",
  "/approvals",
  "/capabilities",
  "/dag-runs",
  "/dags",
]);

export type RecentSurface = {
  path: string;
  /** Epoch ms when the user last left this surface (visibility hidden / navigate away). */
  leftAtMs: number;
  /** Epoch ms when the browsing session that produced `leftAtMs` began. */
  sessionStartedAtMs: number;
};

export type RestoreDecision = {
  path: string;
  reason: "restore" | "default" | "off" | "stale" | "invalid";
};

/** Normalize a recorded path into a restore-eligible surface, or null. */
export function normalizeRestorePath(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const bare = raw.trim().split(/[?#]/, 1)[0] ?? "";
  if (!bare.startsWith("/") || bare.includes("//") || bare.includes("..")) return null;
  if (!RESTORE_SURFACES.has(bare)) return null;
  return bare;
}

/**
 * Decide whether recent-return restores `recent.path` or falls back to the
 * explicit default landing. Precedence matches #1050: recent when still inside
 * the aggressiveness window, else preferred default, else Home baseline.
 */
export function decideLanding(args: {
  aggressiveness: string;
  defaultLanding: string;
  recent: RecentSurface | null;
  nowMs: number;
}): RestoreDecision {
  const aggressiveness = resolveRestoreAggressiveness(args.aggressiveness);
  const defaultLanding = resolveLandingPath(args.defaultLanding);

  if (aggressiveness === "off") {
    return { path: defaultLanding, reason: "off" };
  }
  if (!args.recent) {
    return { path: defaultLanding, reason: "default" };
  }
  const path = normalizeRestorePath(args.recent.path);
  if (!path) {
    return { path: defaultLanding, reason: "invalid" };
  }
  const leftAt = args.recent.leftAtMs;
  const sessionStarted = args.recent.sessionStartedAtMs;
  if (!Number.isFinite(leftAt) || leftAt > args.nowMs) {
    return { path: defaultLanding, reason: "invalid" };
  }
  const awayMs = Math.max(0, args.nowMs - leftAt);
  const absoluteMs = RESTORE_ABSOLUTE_MS[aggressiveness] ?? RESTORE_ABSOLUTE_MS.balanced;
  let windowMs = absoluteMs;
  if (
    (aggressiveness === "balanced" || aggressiveness === "generous") &&
    Number.isFinite(sessionStarted) &&
    sessionStarted > 0 &&
    sessionStarted <= leftAt
  ) {
    const sessionLen = leftAt - sessionStarted;
    const proportion = aggressiveness === "generous" ? 1.0 : 0.5;
    windowMs = Math.max(absoluteMs, sessionLen * proportion);
  }
  if (awayMs > windowMs) {
    return { path: defaultLanding, reason: "stale" };
  }
  return { path, reason: "restore" };
}
