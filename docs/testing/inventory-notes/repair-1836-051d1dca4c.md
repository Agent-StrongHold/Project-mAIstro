---
inventory-delta:
  tests/: +0
---

# Repair round at head 051d1dca4c (L1836, issue #1836) — lint-gate repair, note-only

Round at the assigned head `051d1dca4c983750af1a06fbd795414230c2e3c9` (the
develop sync merge of `80c837d578` into the branch). The prior round
(`e9a7d82230`) committed the V-1…V-18 repro script
`.cursor/context/repro-1836-vectors.py` in a form that fails the repo's
repo-wide ruff gates: the driver's deterministic checks for this job record
`uv run ruff check .` → 9 errors (E401, I001 ×2, **F821 undefined name
`strict_walk_check`**, UP034, C901 complexity 11 > 10, UP017, E402 ×2) and
`uv run ruff format --check .` → 1 file would be reformatted. This round
repairs exactly that file; no production code, spec, ledger, or test file
changed (`tests/: +0`).

## Root-cause fixes applied (no suppressions)

- **F821 (real bug):** removed the never-invoked dead helper `v2_bytes`, whose
  body called the undefined name `strict_walk_check`. All V-1 byte/digest
  constructions were already inline; no vector used the helper.
- **C901:** genuine refactor of `strict_walk` (complexity 11 → ≤10): the
  redundant `isinstance(value, int) and not isinstance(value, bool)` branch
  collapsed to `isinstance(value, int)` (bools already returned in the
  preceding branch — bool is an int subclass), and the non-finite-float check
  extracted verbatim into `_reject_non_finite_float`. Error message strings
  are byte-identical.
- E401/I001/E402: imports split, sorted, and moved into the top block
  (`DurableApproval`/`ApprovalRequest` were imported mid-script at the bottom);
  `copy` hoisted from inside `apply_mutation`.
- UP017 (`timezone.utc` → `datetime.UTC`), UP034 (extraneous parens in
  `v2_digest`), plus `ruff format` normalization of over-long lines.

## Behavior preservation — re-executed live

`uv run python .cursor/context/repro-1836-vectors.py` from the repo root:
**35/35 PASS, rc 0** — identical PASS lines and digests as the prior round
(V-1 digest `v2:8db816aa…8ca82c`, V-3…V-13 mutation table pairwise distinct,
V-15 eight exact TypeErrors, V-16 v1 collision via the production helper,
V-17 escape pin, V-18 legacy digest `1748e5b5…` via unchanged
`approval_request_digest` + `DurableApproval` fallback). The refactor is
proven behavior-preserving, not just lint-clean.

## Gates re-proven at this tree

- `uv run ruff check .` rc 0 ("All checks passed!"); `uv run ruff format
  --check .` rc 0 ("3656 files already formatted") — the two failing driver
  checks now pass.
- Issue-exact deterministic pair: `uv run python
  scripts/check-adr-status-language.py` rc 0; `git diff --check` rc 0.
- Approval seam suites: `uv run pytest
  packages/maistro-core/tests/capabilities/test_durable_approval.py
  packages/maistro-core/tests/capabilities/test_durable_approval_validation.py
  packages/maistro-core/tests/conformance/ -q` → 97 passed, 20 skipped,
  2 xfailed.
- JS supply chain, CI-exact args (`npm audit --package-lock-only --json` in
  each surface): rc 0 with 0 vulnerabilities on all three —
  `packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`,
  `packages/hive-conductor/tests/e2e` (integration-scope root-cause fix
  re-proven after the develop merge touched `package-lock.json`).
- exact-debt-ledger, CI-exact args: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` rc 0 — 1221 reviewed identities == 1221
  findings, base `80c837d578c6`. `git diff --numstat origin/develop --
  quality/` shows only the branch's own `quality/ac-state-notes/auto-1836.json`
  (+17); no baseline rows lost in the develop merge.
- Suite inventory: `uv run python scripts/check-suite-inventory.py` rc 0 —
  21/21 suites match; collected 36486 == unique 36486.

## Gate state (unchanged, by design)

SPEC-101826 stays `status: Proposed`, `contracts: []`; production helper
`packages/maistro-core/src/maistro/capabilities/approval_store.py` unchanged
vs develop (empty diff, `packages/`); owner acceptance by @BlakeMatthews-dev
remains unrecorded — decision gate open by design, no closure action taken.
No GitHub mutation performed from this round.
