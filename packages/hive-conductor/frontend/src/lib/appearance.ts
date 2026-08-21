/** App-level light/dark appearance, distinct from per-workspace themes.
 *
 * Precedence: an active workspace's non-default `theme_id` (fantasia, etc.,
 * applied by WorkspaceContext) always wins; otherwise the user's stored
 * appearance choice applies; with nothing stored we follow the OS
 * `prefers-color-scheme`. Dark rides the existing `[data-theme="dark"]`
 * token set in themes/dark.css -- the same attribute the workspace theme
 * system already uses, so no component needs to know which of the two
 * mechanisms set it.
 */

const STORAGE_KEY = "hive_appearance";

export type Appearance = "light" | "dark";

export function getStoredAppearance(): Appearance | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw === "light" || raw === "dark" ? raw : null;
}

export function resolveAppearance(): Appearance {
  const stored = getStoredAppearance();
  if (stored) return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Stamp the resolved appearance onto <html> -- but never clobber a
 * workspace theme another caller has applied (any data-theme value other
 * than our own "dark"). */
export function applyAppearance(): void {
  const current = document.documentElement.dataset.theme;
  if (current && current !== "dark") return;
  if (resolveAppearance() === "dark") {
    document.documentElement.dataset.theme = "dark";
  } else {
    delete document.documentElement.dataset.theme;
  }
}

export function setAppearance(value: Appearance): void {
  localStorage.setItem(STORAGE_KEY, value);
  applyAppearance();
}
