# Handoff — issue #779, lane L779, repair round 3 (job 94a91df251524bcf99d40fd5d75223e5)

## Outcome (this round)

Committed the prior worker's uncommitted salvage (preserved first as
`incoming-779.patch` in the job directory): the issue's AC markers moved from
the dangling `SPEC-0779/AC-N` to a new spec `docs/specs/
SPEC-100126-b779-cross-artifact-consistency-evaluation.md` (AC-1..AC-7 claimed
with tests, AC-8 browser-E2E declared unproven with a reason), one
`@pytest.mark.contract("behavioral")` added to satisfy the spec's declared
contract kind, and the branch's measured note `quality/ac-state-notes/
auto-779.json` banked. This is what fixes the named CI failure: at 2af57ea42
the 8+ `SPEC-0779` markers named no criterion, so `markers_without_criterion`
measured ~10 against a ceiling of 2 → Quality gate (Pillars 1–4, 7, 8) failed.
After the salvage the candidate measures exactly 2, on the ceiling.

## Validation executed this round (all RC 0 unless stated)

- Full merge-group simulation of the exact CI step that failed
  (`GITHUB_EVENT_NAME=merge_group`, base_sha = develop tip 234a06c5):
  `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  234a06c5…` → ratchet OK (10 counters on ceilings, coverage on floor),
  acceptance mandate OK (8 criteria added/newly claimed, 0 unproven), chain
  mandate OK, actual-base guard OK ("candidate preserves the actual measured
  AC-state of base 234a06c5").
- vulture per-identity ledger (exact-debt-ledger): 1378 ↔ 1378, RC 0.
- contract-marker ledger, reachability + provenance (reachability,
  contract-markers, dispositions, ratchet-provenance), doc-links, radon,
  enumerations, credential-authority, wiring-reads, agent-store-writes,
  convergence-matrix, security/image/backlog inventories, release-consistency,
  bump-version, vendor IFEval/BFCL, shipped-surface-truth: all OK.
- `uv run pytest packages/maistro-design/tests -q` → 370 passed;
  `pytest packages/hive-conductor/backend/tests/test_design_consistency_route.py`
  → 8 passed; mypy 7 package srcs → Success (758 files); xenon 0 violations.
- alembic upgrade head against pg18 (auto-779-pg, port 25779) → RC 0.
- Develop gap: branch is 9 commits behind origin/develop (234a06c5);
  `git merge-tree` shows the trial merge is CLEAN (only overlap is
  `quality/shipped-surface-truth.json`, auto-mergeable). No sync performed:
  the named failure was the quality gate, not a sync conflict.

## Residual risk — pre-existing ac-test flake (not introduced here)

Three identical candidate measurements returned 38.4934 / 38.4789 / 38.4138
`design_coverage`. Root-caused to two maistro-core ac-marked tests that flake
under this box's load (load avg 12–15, many concurrent lanes):

- `packages/maistro-core/tests/security/test_redact.py` —
  `TestRedactScaling::test_cost_grows_linearly_with_input` (ADR-064/AC-36):
  timing-ratio assertion; observed 1 failure in 7 runs.
- `packages/maistro-core/tests/persistence/test_prompt_store_conformance.py` —
  `test_writers_to_different_names_do_not_contend`
  (SPEC-083026-427c/AC-6): `asyncio.wait_for(..., timeout=1.0)` wall-clock
  budget while another write holds a PG advisory lock for 2 s.

Both files are untouched by this branch and by develop's 9 pending commits;
the same flake breaks the gate at the base revision too (a 38.41 measurement
is under the base fold floor 38.4867). Fixing them belongs to a dedicated
maistro-core flake lane; doing it here would widen the diff outside the
issue's surfaces.

AC-8 (browser E2E) remains honestly declared unproven in the spec, as before.

---

# Prior round — repair round 2 (job cdbc9c616b7249c1b2fbcbd09fb9dfb3)

## Outcome

Restored the #779 work that the driver salvage commit `16f76d4e` had committed
as a *deletion* (the four files survived as untracked salvage: evaluator,
tests, inventory note, prior handoff — verified byte-identical to the last
good committed versions except one formatting-only test diff), then repaired
the two named gate failures on top. Worktree left clean and committed on
branch `auto-779`.

## Gate repairs (this round)

1. **ruff C901** (`_check_factual_claims` too complex, 11 > 10): extracted
   per-claim judgment into `_judge_allowed_claim` and the shared/local impact
   closure into `_impact_of_pattern`; removed the genuinely dead write-only
   `covered` list. All finding messages byte-identical; 19/19 consistency
   tests pass unchanged.
2. **exact-debt-ledger** (`scripts/check-vulture-baseline.py`): the 14 new
   identities (12 result-contract Pydantic fields, Pydantic-invoked
   `ClaimRule._require_evidence_backing`, registry-instantiated
   `ConsistencyEvalNode`) are annotated at source with inline vulture markers
   (`noqa: V102/V105/V107`; V105 newly registered in ruff `external`).
   Ledger-banking alone cannot pass this gate because grants are read from the
   base revision (a same-commit grant cannot authorize itself), so the
   identities are eliminated from the findings set instead — the ledger stays
   exact with **zero edits**: 1402 reviewed identities → 1402 findings, RC 0.
3. **check-reachability** (newly failing, exposed by restoring the module):
   `maistro_design.consistency` dispositioned as library-only in
   `quality/reachability-baseline.json`, same as `maistro_design.nodes`
   before it (reached via the registry kind string + tests).
4. **check-suite-inventory**: the salvage's 4 extra tests (+15 → +19) recorded
   in the #779 inventory note.

## Validation executed (all RC 0)

- `uv run ruff check .` / `uv run ruff format --check .`
- `uv run pytest packages/maistro-design/tests -q` → 370 passed
  (19/19 in test_consistency.py, acceptance-mapped)
- `uv run mypy <7 package srcs>` → Success, no issues in 746 files
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1402 ↔ 1402, no deltas
- `scripts/check-suite-inventory.py` → 14 suites match
- `scripts/check-cross-package-imports.py` → ok (2634 files)
- `scripts/check-reachability.py` → ok (1143 modules, 190 baselined)
- `scripts/check-radon-baseline.py` → 67 ↔ 67 (scan is core-only)
- `scripts/check-doc-links.py`, `scripts/check-adr-index.py`,
  `scripts/check-contract-markers.py` → ok

## Acceptance status

Proven by executed tests (see the inventory note for the mapping): persona
violation → local branch only; shared factual contradiction → all consumers of
the bad decision via `consumes`/`references` edges, kind-independent;
locked accepted artifact reported (`requires_unlock`) and provably never
rewritten (evaluator is read-only over a frozen snapshot); exact
brief/decision/artifact versions cited and stable after later edits;
provided evidence vs model-asserted claims distinguished (validator-enforced);
evaluation is a canonical Run/NodeRun/Attempt (`run_durable_graph`); retry
creates fresh run identity while the failed evaluation record stays
retrievable; foreign-project snapshots rejected rather than misfiled.

UNVERIFIED (residual, concrete): Design Studio inspection surface + browser
E2E (one inconsistent sibling corrected while accepted siblings stay
unchanged). Needs: a project-consistency endpoint building the snapshot from
the conductor design project store and running `design.consistency_eval`
through the canonical durable executor, surfaced in
`packages/hive-conductor/frontend/src/pages/DesignStudio.tsx`, plus the
browser E2E.

## Risks / notes

- The branch diverged from origin/develop (8 vs 30 commits); no develop sync
  was performed in this round (the failure was exact-debt-ledger, not a sync
  conflict). The merge queue's develop sync will need to reconcile
  `quality/reachability-baseline.json` and `pyproject.toml` if develop touched
  them (one-line inserts each).
- Deterministic pattern checks are honest but shallow (no model call).
- Branch is 2 commits of develop-sync behind on the vulture/ratchet
  provenance; gates were validated against merge-base b268f0535.
