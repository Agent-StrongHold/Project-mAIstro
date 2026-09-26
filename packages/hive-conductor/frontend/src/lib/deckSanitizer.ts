// Compatibility exports for Deck consumers. The trust boundary is owned by
// visualArtifactRenderer so new Design Studio modes cannot fork the allowlist.
export {
  createSanitizedVisualArtifactFragment,
  SanitizedVisualArtifact,
  recommendVisualArtifactTrust,
  sanitizeVisualArtifactMarkup,
  scanVisualArtifactMarkup,
  VISUAL_ARTIFACT_BLOCK_REASONS,
  writeSanitizedVisualArtifact,
  type VisualArtifactBlockReason,
  type VisualArtifactScan,
  type VisualArtifactTrustRecommendation,
} from "./visualArtifactRenderer";

import {
  escapeVisualArtifactText,
  sanitizeVisualArtifactMarkup,
} from "./visualArtifactRenderer";

/**
 * @deprecated Use sanitizeVisualArtifactMarkup for all Design Studio modes.
 * The unknown input type is intentional: stored JSON can outlive the
 * TypeScript model, so a malformed value must fail closed at this boundary
 * too.
 */
export function sanitizeDeckMarkup(markup: unknown): string {
  return sanitizeVisualArtifactMarkup(markup);
}

/** @deprecated Use escapeVisualArtifactText for all Design Studio exports. */
export function escapeDeckText(value: string): string {
  return escapeVisualArtifactText(value);
}
