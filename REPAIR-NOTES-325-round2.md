# Issue #325 repair round 2 — develop sync conflict + CI `test` gate

Starting head `45a3cc5a2`, base `f956a8142` (origin/develop). The previous
round (`280d2874`) ran its full check battery green at `45a3cc5a2`, then began
the develop merge and died on a provider 429 mid-conflict-resolution, leaving
`scripts/check-image-lock-reconciliation.py` with conflict markers (175 ruff
errors downstream).

## What this round did

1. **Resolved the develop sync conflict** (commit `6e6c6449e`). Both sides had
   fixed the same beartype marker-split bug: develop's `f956a8142` carries the
   #1182 set-valued fix (`expected_by_name: dict[str, set[str]]` + a
   `one of ...` mismatch clause); this branch's `3919f579a` carries the
   marker-evaluating fix (dumps the image interpreter's `python_full_version`,
   selects the applicable pin of a split, keeps a documented lenient fallback
   when the version cannot be determined). The branch implementation
   supersedes — it accepts the applicable pin AND still fails a wrong pin of
   the split (`test_marker_split_wrong_pin_for_the_image_python_is_a_skew`),
   which develop's accept-any-set version cannot do. All non-gate develop-side
   changes (#2285 concurrency work, frontend lockfile bumps, trivyignore,
   inventory notes) auto-merged cleanly. The staged tests after the merge were
   develop's tests + the branch's marker-split tests appended; one develop test
   encoded the older contract.

2. **Adapted `test_split_resolution_still_fails_on_a_version_neither_branch_pins`**
   to the branch's stricter contract. The develop version fed a headerless dump
   and expected the lenient `one of` message; under the branch gate a headerless
   dump intentionally falls back to gating nothing
   (`test_marker_split_with_unevaluatable_marker_stays_lenient`). The adapted
   test preserves develop's intent — a pin neither marker row offers still
   fails — by dumping the interpreter version and asserting the gate names the
   applicable pin (`!= beartype==0.22.9` on a 3.13 image). Test count
   unchanged; no inventory delta.

## The CI failures this round closes

- `test` job at `3919f579a`: `npm audit --audit-level=high` exited 1 in
  `packages/maistro-canvas/frontend`. Develop's lockfile bump (merged here)
  clears it — re-run locally: `found 0 vulnerabilities`, exit 0.
- `Coverage gate` job: failed downstream of the same run (its `test` producer /
  audit step); root `tests/`, server, and core suites all pass locally now.

## Validation evidence (all at `6e6c6449e` + test adaptation)

- `uv run ruff check .` / `ruff format --check .` — pass.
- `uv run mypy` (CI's 10-package argument set) — pass, 1102 files.
- `scripts/check-durable-table-inventory.py` — `ok: 123 durable tables, each
  with a declared retention` (includes `security_violations`, `usage_events`).
- `scripts/check-ratchet-provenance.py`, `check-shipped-surface-truth.py`,
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — all pass (1302 identities = 1302 reviewed; no
  ledger amendment needed).
- `scripts/check-suite-inventory.py` — 21 suites match.
- pytest: retention battery 516 passed; `packages/maistro-core/tests/runs` +
  gate tests 1494 passed; full `packages/maistro-core/tests` 16633 passed;
  full `tests/` 5652 passed; `packages/maistro-server/tests` 646 passed.
- `npm audit --audit-level=high` (canvas frontend, CI's exact step) — exit 0.
