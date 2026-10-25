/** Per-account UI state kept in this browser (#1418, #1433).
 *
 * Owned localStorage keys remember conveniences between sessions. None is
 * secret and none is the record; they used to outlive a sign-out and
 * carry over to whoever signed in next on the same browser profile, so a
 * second account opened on the first account's last workspace tab. The
 * keys are now owned: the signed-in user id is stamped beside them, a
 * different user signing in clears them first, and signing out clears them
 * outright. The Profile page lists them, with their values, and can clear
 * them on request. `hive_last_surface` feeds recent-return restore (#1050).
 */

import type { RecentSurface } from "./landing";
import { normalizeRestorePath } from "./landing";

export const UI_STATE_KEYS = [
  { key: "hive_active_workspace_id", what: "The workspace tab you last had open" },
  { key: "hive_appearance", what: "Light or dark, when you chose one over the system setting" },
  { key: "hive_onboarded", what: "That the welcome tour has been dismissed" },
  {
    key: "hive_last_surface",
    what: "The last Workspace surface for recent-return restore (#1050/#1822)",
  },
] as const;

/** localStorage key for the recent-return surface blob (JSON RecentSurface). */
export const LAST_SURFACE_KEY = "hive_last_surface";

const OWNER_KEY = "hive_ui_state_owner";

// The Simple/Power toggle never gated anything observable and is gone
// (#1409, #1411); a browser that stored it before this shipped still gets
// it swept on the next clear, same as any other owned key, without a row
// on the Profile page for a control that no longer exists.
const _LEGACY_KEYS = ["hive_ui_mode"] as const;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Every owned key with its current value, for the Profile page. */
export function storedUiState(): { key: string; what: string; value: string | null }[] {
  return UI_STATE_KEYS.map(({ key, what }) => ({ key, what, value: read(key) }));
}

/** Forget every owned key and the owner stamp. Called on sign-out. */
export function clearUiState(): void {
  try {
    for (const { key } of UI_STATE_KEYS) localStorage.removeItem(key);
    for (const key of _LEGACY_KEYS) localStorage.removeItem(key);
    localStorage.removeItem(OWNER_KEY);
  } catch {
    // Storage unavailable (private window, blocked): nothing was kept.
  }
}

/** Stamp the signed-in user as the owner of the stored state, clearing it
 * first when it belonged to someone else. Returns true when it was cleared.
 * A missing stamp (state written before this existed) is left alone: it is
 * as likely this user's as anyone's, and sign-out clears it from now on. */
export function claimUiState(userId: string): boolean {
  const owner = read(OWNER_KEY);
  if (owner === userId) return false;
  const cleared = owner !== null;
  if (cleared) clearUiState();
  try {
    localStorage.setItem(OWNER_KEY, userId);
  } catch {
    // Same as above.
  }
  return cleared;
}

/** Read the recent-return surface, or null when missing/corrupt/ineligible. */
export function readLastSurface(): RecentSurface | null {
  const raw = read(LAST_SURFACE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<RecentSurface>;
    const path = normalizeRestorePath(parsed.path);
    if (!path) return null;
    const leftAtMs = Number(parsed.leftAtMs);
    const sessionStartedAtMs = Number(parsed.sessionStartedAtMs);
    if (!Number.isFinite(leftAtMs) || !Number.isFinite(sessionStartedAtMs)) return null;
    return { path, leftAtMs, sessionStartedAtMs };
  } catch {
    return null;
  }
}

/** Persist the surface the user is about to leave (or just left). */
export function writeLastSurface(surface: RecentSurface): void {
  const path = normalizeRestorePath(surface.path);
  if (!path) return;
  try {
    localStorage.setItem(
      LAST_SURFACE_KEY,
      JSON.stringify({
        path,
        leftAtMs: surface.leftAtMs,
        sessionStartedAtMs: surface.sessionStartedAtMs,
      }),
    );
  } catch {
    // Storage unavailable — restore simply will not fire.
  }
}
