// Compatibility exports for Deck consumers. The trust boundary is owned by
// visualArtifactRenderer so new Design Studio modes cannot fork the allowlist.
export {
  createSanitizedVisualArtifactFragment,
  SanitizedVisualArtifact,
  recommendVisualArtifactTrust,
  sanitizeVisualArtifactMarkup,
  scanVisualArtifactMarkup,
  VISUAL_ARTIFACT_BLOCK_REASONS,
  type VisualArtifactBlockReason,
  type VisualArtifactScan,
  type VisualArtifactTrustRecommendation,
} from "./visualArtifactRenderer";

import {
  escapeVisualArtifactText,
  sanitizeVisualArtifactMarkup,
} from "./visualArtifactRenderer";

/**
 * Sanitize untrusted Deck markup through the one shared #768 boundary.
 *
 * @deprecated New Deck code should call `sanitizeVisualArtifactMarkup`
 * directly; this wrapper stays so Deck consumers cannot fork the allowlist.
 * The unknown input type is intentional: stored JSON can outlive the
 * TypeScript model, so a malformed value must fail closed at this boundary.
 */
export function sanitizeDeckMarkup(markup: unknown): string {
  if (typeof markup !== "string" || !markup) return "";
  return sanitizeVisualArtifactMarkup(markup);
}

/** @deprecated Use escapeVisualArtifactText for all Design Studio exports. */
export function escapeDeckText(value: string): string {
  return escapeVisualArtifactText(value);
}
