---
inventory-delta:
  packages/maistro-design/tests: +14
---
# #817 round 14 — develop sync resolution (920fb384e + ca4caec7d) and log-redaction idempotence repair

## Ledger repair note (recorded at 13775de35)

This note's front matter was malformed from birth: the opening `---` delimiter
was missing, so `check-suite-inventory.py` never parsed its delta and the
design-suite movement from the behavior/-moz-binding value anchor went
unrecorded (the verifier's `check-suite-inventory.py --suite
packages/maistro-design/tests` failed with `expected 310, collected 324`).
`--update` recorded the missing `packages/maistro-design/tests: +14`.

The original front matter also claimed `packages/maistro-core/tests: +3`.
That number was wrong: it counted the three net assertion lines added to
`test_install_is_idempotent`, not pytest node IDs — assertions inside existing
tests do not move collection, and the core gate has matched at 11132 before
and after the change. The core delta is therefore correctly absent from the
ledger, and the stale uncounted remnant block is removed here rather than
left as dead body text implying a core movement that never happened.

## What this round changed

The preserved develop-sync merge conflict in `auto-817` was resolved and committed
(merge commit `775d54ac2`), then `origin/develop` (`ca4caec7d`, #1446 RSI harvest
boundary) was merged on top (`3925106f2`, clean auto-merge).

- `packages/maistro-core/src/maistro/security/normalize.py`: union of both lines —
  entity/CSS escape decoding first, then NFKD / invisible stripping / homoglyph
  folding, then bounded leetspeak folding. Both behaviors are pinned by the
  merged `test_detector.py` (CSS hex-escape table + leetspeak corpus).
- `packages/hive-conductor/frontend/src/pages/DeckBuilder.tsx`: develop's
  keyboard-complete editor (#370) with every sink routed through the shared #768
  `visualArtifactRenderer` boundary directly (`sanitizeVisualArtifactMarkup` /
  `escapeVisualArtifactText`) instead of the deprecated `deckSanitizer` shim.
- `packages/hive-conductor/frontend/src/pages/DesignStudio.tsx`: develop's
  routing (`DeckBuilder` / `FixedPageEditor`). `FixedPageEditor` renders escaped
  layer text only — no raw-markup sink; `FixedPageArtifactEditor` remains the
  shared-boundary hostile-corpus fixture exercised by
  `deck-sanitization.spec.ts`.
- `packages/maistro-core/tests/security/test_log_redaction.py` (+3 lines of
  assertions, net): `test_install_is_idempotent` assumed a second
  `install_log_redaction` call wraps nothing. pytest 9 (`catching_logs` in
  `_pytest/logging.py`) attaches `LogCaptureHandler`s to **every
  non-propagating logger**, including the fixture's `maistro.test.redaction`
  logger, between fixture setup and the test body — so the second install
  correctly wraps those foreign handlers and returned 2. Production behavior is
  correct (handlers added after install SHOULD be covered); the test now
  asserts the actual idempotence contract: handler count unchanged, every
  handler wrapped exactly once (`RedactingFormatter`, inner not
  `RedactingFormatter`).

## Validation executed on the merged tree

- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run pytest packages/maistro-core/tests/security packages/maistro-core/tests/runs -q` — 2205 passed, 228 skipped.
- `uv run --package maistro-design pytest packages/maistro-design/tests -q` — 310 passed.
- `uv run pytest packages/maistro-rsi/tests -q` — 779 passed (incoming #1446/#1138 suites).
- `uv run pytest packages/maistro-turing/tests packages/maistro-server/tests/api -q` — 562 passed.
- Frontend: `tsc -p tsconfig.json --noEmit` clean; `eslint` on the two resolved
  pages clean.
- `deck-sanitization.spec.ts`: **8/8 passed in real Chromium** against the live
  worktree sources (harness bundling the resolved `DeckBuilder.tsx`,
  `FixedPageArtifactEditor.tsx`, `deckSanitizer.ts`, `visualArtifactRenderer.tsx`;
  zero attacker requests asserted per test). Local harness env:
  `E2E_SRC_ROOT=<package root> E2E_NODE_PATHS=<frontend>/node_modules`.
- Independent 15-probe hostile corpus through `scan_and_record` vs
  `scan_design_text`: 14 → SKULL/banish/0.9 with explicit shared flags and
  output boundary block; 1 heuristic-only → T3/keep/0.6 with flag; clean control
  → T3/upgrade/0.0/0 flags and boundary pass. No upgrade-on-blocked case.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — rc=0, 1412 reviewed identities.
- `scripts/verify-monorepo-layout.sh` ok; `scripts/check_enumerations.py` ok.

## Behavior/-moz-binding value anchor (round-14 follow-up fix)

Running the full Conductor backend suite on the merged tree exposed a
pre-existing (present at `d0e549f72`) false positive: the shared CSS
`network/code` primitive pattern matched bare `behavior\s*:` /
`-moz-binding\s*:` in English prose, so `start_design_service` generation
against the bundled `apple` system was trust-banned on its own
"**Container behavior:**" prompt-stack heading. The properties exfiltrate only
when the declaration names a payload, so both vocabulary copies
(`warden/patterns.py` SCRIPT + VISUAL_ARTIFACT tables, kept in lockstep with
`maistro_design/scan.py`'s `_css_network_or_code_is_blocking` verdict) now
require a URL-or-function value (`url(`, `expression(`, scheme, `//`, or a
relative path) after the colon.

New pins: `test_scan.py::test_behavior_binding_value_payloads_are_blocking`
(5 payload forms stay blocked), `test_scan.py::test_behavior_prose_is_not_a_css_primitive`
and `test_trust_prescan.py::test_behavior_prose_gets_no_blocking_flag_and_stays_upgradeable`
(prose stays renderable and upgradeable), plus 2 payload entries in the
`HOSTILE_CORPUS` pre-scan parity corpus.

## Residual

- Full Playwright UI suites that need the live stack
  (`design-studio-keyboard.spec.ts`, `design-studio-truthfulness.spec.ts`) were
  not run locally (no backend up); tsc + eslint + the 8/8 boundary spec cover
  the merged frontend files' compile-time and boundary behavior. CI's
  `hive-conductor-e2e-ui` job exercises the routed journeys.

## Round-15 repair validation (inventory-ledger round at 13775de35)

- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run pytest packages/maistro-design/tests -q` — 324 passed.
- `uv run pytest packages/maistro-core/tests/security -q` — 1325 passed, 19 skipped.
- `.venv/bin/python -m pytest packages/hive-conductor/backend/tests/test_design_renderers.py -q` — 7 passed.
- Live 10-case hostile probe through `scan_and_record` vs `scan_design_text`
  (script tag, event handler, script-capable SVG, `data:text/html`, CSS `url()`,
  CSS `@import`, `behavior:`/`-moz-binding:` payloads, CSS hex-escape `\75rl(`,
  prompt injection): every case SKULL + `banish` + explicit shared flags on the
  pre-scan, blocked at the output boundary, output flags a subset of pre-scan
  flags (AC-1..AC-4); clean control stays T3/`upgrade`/0 flags.
- `scripts/check-suite-inventory.py` — ok: 13 suite(s) match the recorded
  inventory (design suite at 324 after the recorded +14).
