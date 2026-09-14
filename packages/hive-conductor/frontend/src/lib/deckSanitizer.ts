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

/** @deprecated Use sanitizeVisualArtifactMarkup for all Design Studio modes. */
export function sanitizeDeckMarkup(markup: string): string {
  return sanitizeVisualArtifactMarkup(markup);
}

/** @deprecated Use escapeVisualArtifactText for all Design Studio exports. */
export function escapeDeckText(value: string): string {
  return escapeVisualArtifactText(value);
}
