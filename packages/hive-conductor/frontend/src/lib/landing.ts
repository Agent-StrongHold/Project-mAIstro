/**
 * Workspace product preferences on the canonical profile (#1050).
 *
 * Stored under `preferences.*` so UI, PATCH /v1/profile, and chat
 * `profile_set` share one durable owner. Fresh accounts with no preference
 * land on Workspace Home with balanced restore aggressiveness.
 */

export const LANDING_PREF_KEY = "workspace_default_landing";
export const RESTORE_PREF_KEY = "workspace_restore_aggressiveness";
/** path → epoch-ms until which a learned-landing proposal stays quiet (#1050). */
export const SUGGESTION_COOLDOWN_PREF_KEY = "workspace_landing_suggestion_cooldown";

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

// ── Bounded learned-landing suggestion (#1050) ─────────────────────────
//
// Observes immediate hops from the default/Home surface to another landing
// option. After a configurable streak (policy knob, not product law) the SPA
// may show a non-blocking proposal. Accept writes the durable profile default;
// dismiss suppresses further nags for that path. Explicit default ≠ Home
// outranks learning — no proposal while the user already pinned a surface.

/** How soon after arriving on Home/default a leave counts as "immediate". */
export const LEARNED_IMMEDIATE_MS = 45_000;

/**
 * Minimum consistent immediate hops before a proposal is worth showing.
 * Configurable policy — deliberately not a fixed "magic" product count in the
 * issue; this is the SPA's published band for tests and the UI.
 */
export const LEARNED_STREAK_MIN = 3;

/**
 * How long dismiss/"Not now" keeps a learned proposal quiet. Stored on the
 * durable profile (`SUGGESTION_COOLDOWN_PREF_KEY`) so a return does not re-nag.
 */
export const LEARNED_SUGGESTION_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;

export type LandingNavPattern = {
  path: string;
  streak: number;
  lastAtMs: number;
};

export type LandingSuggestion = {
  path: string;
  streak: number;
};

export type LandingSuggestionDecision =
  | {
      show: false;
      reason: "explicit" | "suppressed" | "cooldown" | "insufficient" | "ineligible";
    }
  | { show: true; suggestion: LandingSuggestion };

/** Record an immediate Home→surface hop; returns the updated streak pattern. */
export function recordImmediateLandingHop(
  prior: LandingNavPattern | null,
  path: string,
  nowMs: number,
): LandingNavPattern | null {
  const target = resolveLandingPath(path);
  if (target === DEFAULT_LANDING_PATH) return prior;
  if (!ALLOWED_LANDING.has(target)) return prior;
  if (prior && prior.path === target) {
    return { path: target, streak: prior.streak + 1, lastAtMs: nowMs };
  }
  return { path: target, streak: 1, lastAtMs: nowMs };
}

/** Normalize the durable dismiss-cooldown map (path → until epoch-ms). */
export function resolveSuggestionCooldown(raw: unknown): Record<string, number> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const path = resolveLandingPath(key);
    if (path === DEFAULT_LANDING_PATH) continue;
    const until = Number(value);
    if (!Number.isFinite(until) || until <= 0) continue;
    out[path] = Math.floor(until);
  }
  return out;
}

/** Merge a dismiss for `path` into the cooldown map; prune expired entries. */
export function mergeSuggestionCooldown(
  prior: unknown,
  path: string,
  nowMs: number,
  cooldownMs: number = LEARNED_SUGGESTION_COOLDOWN_MS,
): Record<string, number> {
  const current = resolveSuggestionCooldown(prior);
  const pruned: Record<string, number> = {};
  for (const [p, until] of Object.entries(current)) {
    if (until > nowMs) pruned[p] = until;
  }
  const target = resolveLandingPath(path);
  if (target !== DEFAULT_LANDING_PATH) {
    pruned[target] = nowMs + Math.max(0, cooldownMs);
  }
  return pruned;
}

/**
 * Decide whether to propose making `pattern.path` the default landing.
 * Explicit non-Home default, local suppress, and profile cooldown suppress
 * without nagging. Learned defaults are never applied silently — accept only.
 */
export function decideLandingSuggestion(args: {
  pattern: LandingNavPattern | null;
  explicitDefault: string;
  suppressedPaths: ReadonlySet<string>;
  cooldownUntilByPath?: Readonly<Record<string, number>>;
  nowMs?: number;
  streakMin?: number;
}): LandingSuggestionDecision {
  const explicit = resolveLandingPath(args.explicitDefault);
  if (explicit !== DEFAULT_LANDING_PATH) {
    return { show: false, reason: "explicit" };
  }
  const pattern = args.pattern;
  if (!pattern) return { show: false, reason: "insufficient" };
  const path = resolveLandingPath(pattern.path);
  if (path === DEFAULT_LANDING_PATH || !ALLOWED_LANDING.has(path)) {
    return { show: false, reason: "ineligible" };
  }
  if (args.suppressedPaths.has(path)) {
    return { show: false, reason: "suppressed" };
  }
  const nowMs = args.nowMs ?? Date.now();
  const until = args.cooldownUntilByPath?.[path];
  if (typeof until === "number" && until > nowMs) {
    return { show: false, reason: "cooldown" };
  }
  const min = args.streakMin ?? LEARNED_STREAK_MIN;
  if (pattern.streak < min) {
    return { show: false, reason: "insufficient" };
  }
  return { show: true, suggestion: { path, streak: pattern.streak } };
}
