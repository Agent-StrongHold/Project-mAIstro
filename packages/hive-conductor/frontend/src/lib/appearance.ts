/** App-level light/dark scheme, distinct from per-workspace persona themes.
 *
 * The Workspace tokens (themes/workspace-tokens.css) split the two axes the
 * old stylesheet conflated: `data-scheme` on <html> is light or dark and is
 * the user's choice (or the OS preference when nothing is stored);
 * `data-theme` is the workspace's persona template (greenhouse, slate,
 * studio) and is set by WorkspaceContext. Every persona has both schemes, so
 * neither axis ever needs to know about the other.
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

/** Stamp the resolved scheme onto <html>. Light is the tokens' `:root`, so it
 * is the absence of the attribute rather than a value of its own. */
export function applyAppearance(): void {
  if (resolveAppearance() === "dark") {
    document.documentElement.dataset.scheme = "dark";
  } else {
    delete document.documentElement.dataset.scheme;
  }
}

export function setAppearance(value: Appearance): void {
  localStorage.setItem(STORAGE_KEY, value);
  applyAppearance();
}
