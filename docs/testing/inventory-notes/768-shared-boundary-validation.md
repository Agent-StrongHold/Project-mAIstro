inventory-delta:
  - validated that hostile content is blocked by the trust pre-scan (scan_and_record returns SKULL)
  - validated that safe content has no visual artifact reasons
  - verified that the trust pre-scan uses the shared visual artifact scan (mirroring the frontend)
  - verified that Deck uses the shared boundary via the deprecated sanitizeDeckMarkup
  - verified that fixed-page modes use the shared boundary via sanitizeVisualArtifactMarkup

---

# 768 shared-boundary validation

## Re-validation round at 997e843b0 (2025, lane auto-768)

All four prior findings were re-checked against production behavior and are
non-reproducing at this head; acceptance evidence was re-executed, not
assumed:

1. `trust.py` recommendation=upgrade for active markup — non-reproducing:
   executed `scan_and_record` on hostile SVG
   (`<script>` + `<foreignObject>` + `onload`) in-repo; result was
   `tier=skull`, `recommendation=banish`, flags include `active-element`,
   `dangerous-url`, `unsupported-attribute` (folds
   `scan_visual_artifact_markup`, #817 parity).
2. `deck-sanitization.spec.ts` trust check via test-harness global —
   non-reproducing: the spec now reads `data-trust-recommendation` from the
   shipped `FixedPageArtifactEditor` (spec lines ~372-388); the global is
   used only for raw sanitizer/scan probes.
3. `DesignStudio.tsx` fixed-page editor without loaded/stored path —
   non-reproducing: editor mounts with `initialMarkup` /
   `initialTrustRecommendation` / `onMarkupChange`; `loadPersistedArtifacts`
   sanitizes legacy localStorage payloads on read and rewrites them;
   availability matrix distinguishes deck (closed) from fixed-page modes
   (edit/preview available, export available).
4. `pytest` collection ImportError (`get_settings` from
   `packages/maistro-core/tests/config/__init__.py`) — non-reproducing:
   `uv run pytest packages/maistro-core/tests -q` → 10173 passed, 654
   skipped, 1 xfailed.

Executed acceptance evidence at this head:

- `docker build -f tests/Dockerfile.playwright .` (context
  `packages/hive-conductor`), then in-container:
  - `visual-artifact-boundary.spec.ts` → 3 passed (single executable sink;
    pattern self-test; per-surface shared-renderer consumption).
  - `deck-sanitization.spec.ts` → 8 passed (Deck hostile corpus;
    paste/drop/DOM-edit/export; malformed stored values fail closed;
    mutation/encoded/SVG/CSS families; deck templates; poster + infographic
    + flyer preview/edit/export with `attackerRequests == []`).
- Full compose stack (`docker-compose.test.yml`, this worktree's hive,
  port override, no repo edits):
  `design-studio-truthfulness.spec.ts` → 5 passed, including
  "fixed-page artifacts rehydrate through the shared boundary" against the
  live app (localStorage re-injection, sanitize-on-read, verdict survives
  reload).
- `uv run pytest packages/maistro-design/tests -q` → 287 passed
  (incl. `test_trust_prescan.py`: blocked markup is never recommended
  upgrade; upgrade recommendation matches shared scanner verdict).
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `scripts/check-suite-inventory.py` → 13 suites match;
  `check-security-inventory.py`, `check-doc-links.py`,
  `check-frontend-api-routes.py`, `check-shipped-surface-truth.py` → ok.
