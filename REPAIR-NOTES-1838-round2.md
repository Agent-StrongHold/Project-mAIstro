# REPAIR-NOTES-1838 round 2 — rebuild-clobber resolution (job 0d4e5ed4)

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; develop base `4de7e906d9dc`; starting head `0e9425759b06`.

## What was wrong (evidence, not guesses)

The starting head was an orchestrator-built reconstruction ("rebuild L1838: re-apply
orphaned lane history onto develop (was f86fe3302c, root b1c9eafb94)"). The orphaned
lane history was rooted at an old develop, so re-applying it wholesale **reverted
merged develop work**: 471 files changed vs the base, net −22k lines, including CI
gate ledgers. The prior round (job `1227a063d02c4b2a94974e919ee466da`) died on a
provider 429 before any check ran; no `check-*.log` files exist for this job.

Failures reproduced before any repair:

| Gate | Failure at starting head | Cause |
|---|---|---|
| `scripts/check-adr-index.py` (CI `registry.yml` §"ADR-INDEX agrees with ADR front matter") | FAIL — 7 × "ADR exists but is missing from the index" (ADR-104, ADR-105, ADR-100126-5445, ADR-100526-9c55, ADR-100526-be49, ADR-100826-c0e1, ADR-101726-e4bb) | rebuild dropped 7 rows that exist in the base index; files untouched |
| `scripts/check-suite-inventory.py` | FAIL — 6 × "listed in the table but with no collection recipe" (reference-greeter, 4 gallery suites, maistro-ext-harness) | rebuild deleted the six `RECIPES` entries (#951/#980/#974) added on develop |
| `scripts/check-suite-inventory.py` (next layer) | FAIL — "collection recipes with no baseline count" (same 6 + `maistro-ext-sdk`) | rebuild replaced `docs/testing/inventory/baseline.json` counts with stale values from the old lane tree and dropped 8 suite rows |
| `scripts/generate-spec-ac-defined-index.py` + `git diff --exit-code docs/specs/README.md` (CI `registry.yml`) | DRIFT | rebuild dropped the SPEC-100826-c0e1 row (same clobber pair as its ADR row) |
| `pyproject.toml`, `docs/testing/SUITE-INVENTORY.md`, plus ~460 further paths | silent reversion of develop content | re-application of the old-lane diff |
| alembic | 3 stale re-additions (`041_canonical_run_effect_claim`, `043_capability_invocation_effect_index`, `045_capability_invocation_logical_effect`) whose content develop already carries renumbered (`034_canonical_run_effect_claim`, `043_invocation_quota_door`, `046_durable_elevation_grants`) | duplicate/ambiguous migration heads |

Environment note: the first `uv sync` in this environment had never completed (uv.lock
parse hiccup), leaving the dev-extra extension packages uninstalled, which made
`check-suite-inventory.py` collection fail with `ModuleNotFoundError: reference_greeter`
on **both** the base and head trees. Fixed by running `uv sync --locked --extra dev`;
the gate then passes with develop's own ledgers.

## Resolution

Two commits on top of the rebuild:

1. `5e2a129db` — partial in-place repair (7 index rows + 6 recipes restored verbatim
   from base), committed first as salvage.
2. `998226437` — complete develop-sync-style resolution: develop's side of all 465
   clobbered paths restored verbatim from `4de7e906d9dc`; the 3 stale alembic files
   removed; **the sole issue-#1838 deliverable kept** —
   `docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md` plus its single
   ADR-INDEX row.

Nothing was rebased, reset, or force-cleaned; every intermediate state remains
reachable in git history. Final branch delta vs develop is exactly 2 files
(+303 lines): the Prospective ADR and one index row.

## Validation after resolution (all executed locally)

- `uv run python scripts/check-adr-status-language.py` → PASS (issue's deterministic acceptance)
- `git diff 4de7e906d9dc..HEAD --check` → PASS (issue's deterministic acceptance)
- `scripts/check-adr-index.py` → PASS
- `scripts/check-adr-status-language-provenance.py` → PASS (0 contradictions, no expansion)
- `scripts/check-citation-status-provenance.py` → PASS
- `scripts/generate-spec-ac-defined-index.py` + `git diff --exit-code docs/specs/README.md` → PASS (in sync)
- `scripts/check-suite-inventory.py` → PASS (21/21 suites match the recorded inventory; 34,125 unique node IDs)
- `uv run ruff check .` → PASS
- `maistro_registry.validator.validate_file` on the ADR → 0 errors, 0 warnings
  (only the intentional test-evidence debt: `tests: []` stays empty — the issue forbids
  claiming an implementation test from a document gate)

## Issue-acceptance boundary (stays open by design)

The ADR records the full adapter contract (biscuit-python 0.4.0 / `biscuit_auth`,
Rust core `biscuit-auth` 6.0.0, Ed25519-only, module path
`packages/maistro-core/src/maistro/capabilities/biscuit_adapter.py`, pinned vector
corpus, dependency owner `@BlakeMatthews-dev`) with status **Proposed**. The named
owner's explicit review is the gate; per the issue's own terms the hygiene commands
"cannot prove a policy decision or security review", so issue #1838 stays open and no
implementation is claimed or authorized here.

## Test/inventory deltas

None. No test files added or changed; no inventory note required (the suite-inventory
baseline and notes are byte-identical to develop's).
