---
inventory-delta:
  tests/: +0
---

# cr1532-verifier-validation-010d5afa9

Repair/validation round for PR #1532 (retire body status lines,
ADR-092126-a28a). Starting/ending head is the already-merged
`010d5afa90f758b53c4961741ef332413128ff73`; `origin/develop` base is
`221dc3d517e7580dc80859259cfdf15a2fd3ec9e`. No tree edits were required for
the issue-specific gates; this note records the evidence run.

Gates re-run with CI's exact arguments, all exit 0 for the #1532 surface:

- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run python scripts/check-adr-status-language.py` — ok: 0 baselined
  body-status contradiction(s), no new ones, none stale.
- `uv run python scripts/check-adr-status-language-provenance.py` — ok:
  metric v2, 0 current body-status finding(s), no candidate-approved
  expansion.
- `uv run python scripts/check-adr-index.py` — ok: every ADR-INDEX row
  agrees with its ADR's front matter.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (quality.yml vulture
  ratchet) — 1221 reviewed identities, 1221 findings, unclassified 0;
  baseline `221dc3d517e7`, candidate `010d5afa90f7`. No ledger amendment
  needed.
- `uv run python scripts/check-ratchet-provenance.py` — 0 lifecycle
  violations; 55 quality JSON consumers with explicit provenance.
- `uv run python scripts/check-suite-inventory.py` — 21 suite(s) match the
  recorded inventory; 36,563 collected node IDs, 0 duplicate identities.
- `uv run pytest tests/test_check_adr_status_language.py
  tests/test_check_adr_status_language_provenance.py
  tests/test_check_adr_index.py -q` — 135 passed, 0 failed.
- `maistro_registry.cli lint . --strict` — 446 files checked, 0 errors,
  0 warnings, 0 extra; existing test-evidence debt remains visible.

Acceptance evidence (ADR-092126-a28a AC-1..AC-4):

- AC-1: `grep` for bare and list-item `**Status:**` body lines across
  `docs/adr/` and `docs/specs/` returns zero matches; the gate corpus audit
  returns zero findings.
- AC-2/AC-3: parametrized tests prove an agreeing body status line fails in
  bare/dash/star/plus/ordered spellings and 0–3 leading spaces, for both ADR
  and spec roots; disagreeing value, trailing prose, and empty value cases
  also fail.
- AC-4: banner-naming-wrong-replacement and unqualified status-stays prose on
  a Superseded document still fail independently.

Residual risks recorded for the integrator:

- Hosted CI at exact head `010d5afa90f7` reports failures in `Coverage gate`,
  `lint-and-type-check`, and `test` (dispatch-context capture
  2026-11-25T06:36). These are outside the #1532 acceptance surface and are
  not reproduced by the focused gates above.
- Commits `e9aad7356` and `0df275362` remain in branch ancestry with
  `Closes #1127, #1098, #1056, #1109, #1143` / `(Closes #76 AC-2)` in their
  messages; `scripts/check-closure-targets.py` scans only PR title/body, so a
  merge would auto-close those still-open issues independent of verification.
