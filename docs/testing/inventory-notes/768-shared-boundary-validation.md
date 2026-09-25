inventory-delta:
  - validated that hostile content is blocked by the trust pre-scan (scan_and_record returns SKULL)
  - validated that safe content has no visual artifact reasons
  - verified that the trust pre-scan uses the shared visual artifact scan (mirroring the frontend)
  - verified that Deck uses the shared boundary via the deprecated sanitizeDeckMarkup
  - verified that fixed-page modes use the shared boundary via sanitizeVisualArtifactMarkup
