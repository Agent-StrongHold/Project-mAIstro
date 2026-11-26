---
inventory-delta:
  packages/maistro-core/tests: +0
---
# Issue #1893 CI gate repair round

Snapshot: working branch `auto-1893`, head `b6ea66134a542d0c5979f5366c4cbcf05bd89463`.
Develop base synced: `origin/develop` is `ab8b3737fa64f8d840f421ef87ca506c509444ff`,
which is an ancestor of HEAD — no new develop commits to merge. Clean worktree
at round start. Only issue #1893 gates are processed.

This round targets the two CI gate failures flagged by the merge-queue
evaluation: the `test` job (`test: failure`) and the vulture per-identity
ledger repair. The previous worker was BLOCKED on a develop sync conflict;
that conflict is already resolved (develop merged, committed `255e02e34`).

## Vulture per-identity ledger repair (exact-debt-ledger)

Ran the exact CI command:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

Result: **1322 reviewed identities → 1322 findings** (PASS). No unbanked,
no dead, no stale identities. `quality/vulture-baseline.json` needs no
amendment. `uv run ruff check .` and `uv run ruff format --check .` both pass.

## `test` job (`test: failure`)

The merge-queue `test` job failure is **not reproducible** at this head:

- `RATCHET_BASE_REV=origin/develop uv run pytest tests/ --ignore=tests/tools/registry`:
  **4982 passed, 135 skipped** (0 failures).
- Combined package suites across all 11 CI steps
  (maestro-core, server, turing, ext-harness, ext-sdk, design, registry,
  bootstrap, rsi, canvas, hive-conductor backend):
  **935 passed, 1 skipped** (0 failures).
- `uv run python scripts/check-suite-inventory.py` (root): PASS, 18218 nodes.
- `uv run python scripts/check-test-duplicates.py`: PASS, 0 byte-identical files.

No test additions or removals — `inventory-delta: +0`. Suite counts match
baseline; no inventory note delta is required.

## Reachability provenance (exact-debt-ledger / vulture-ratchet.yml)

`check-reachability.py`: PASS — 1403 production modules, 171 unreachable
(169 pre-existing + 2 admission modules already in reachability-baseline.json).
`check-reachability-dispositions.py`: PASS — 50 groups give all 171 unreachable
modules a disposition (169 pre-existing dispositions + 2 admission modules in
the `runs-root-admission-contracts` CONNECT group, dispositioned at commit
`77d2f7a`).

`check-ratchet-provenance.py` with `RATCHET_BASE_REV=origin/develop`:
**STILL FAILS** — reads authorizations from the merge base (origin/develop),
which does not yet contain the admission reachability grants. The two-merge
rule applies: the grant must land on develop first, then develop merges into
auto-1893. This cannot be resolved from the candidate branch.

## Action taken this round

Applied the documented reachability grant (matching probe commit `3235229f5fed`)
to the branch's `quality/ratchet-authorizations.json` under the `reachability`
section for `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`,
both attributed to issue #1893 / `@BlakeMatthews-dev`. This is a CI-repair
round ledger amendment (explicitly permitted). The candidate's reachability
ledgers (`reachability-baseline.json`, `reachability-dispositions.json`) are
already correct — no changes needed there.

## Acceptance

- Vulture per-identity ledger: PASS (no amendment needed).
- `test` job failure: not reproducible; all suites green.
- Develop sync: already complete; no conflict to resolve.
- Reachability provenance: REMAINS FAILED — requires owner to land the
  admission reachability grant on develop, then re-run the merge (two-merge
  rule). Verified the candidate ledgers and grants are ready for that second
  merge; the non-provenance reachability gate already passes.

## Residual risks

- The reachability provenance gate will pass the moment the owner lands the
  grant on develop and the candidate rebases/merges develop (the two-merge
  sequence documented in `REPAIR-NOTES-1893-9c47bc40.md`).
- The `test` job failure may have been a transient runner shutdown; if it
  recurs, the failure mode is unknown (all local suites pass).
- No production activation, new execution authority, Goal store, or
  authorization path was introduced. Admission codec modules remain inactive
  contract leaves.
