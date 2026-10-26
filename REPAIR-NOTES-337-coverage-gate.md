# REPAIR-NOTES — #337 round: clear the diff-coverage gate + conclude the develop sync

Job `636a67ff94ad4d09899f3268e1c51b9e`, branch `auto-337`. Incoming head
`c06a25c72bf0` (the prior verify head). Two carried blocks: the red
`Coverage gate (publish-set floor + diff coverage)` from the last
merge-queue evaluation, and the stale "worker made no commit" block (the
tree was clean at `c06a25c72`; the work below is the new commit).

## 1. The red gate: root cause

The only red check at `c06a25c72` was the diff-coverage leaf:

```
packages/hive-conductor/backend/services/feedback_service.py: 16.7% of 6
changed lines (need 90%); uncovered 201, 202, 223, 224, 232
```

Those five lines are the body of `feedback_service.record_outcome`, added
at `46b0986d1`. `grep` over `packages/` and `tests/` finds no production
caller and no test for it; `DagRunStore.record_outcome` is the owner of
general outcome writes (#1036 terminality), so the feedback copy was dead.
It is exactly the "unused setter or optional wiring implies durability
that no path consumes" pattern issue #337's acceptance criteria forbid.

## 2. The repair

Remove the unused `record_outcome` function (commit `a4b820e14`, −66
lines). The durability story for feedback is unchanged and still complete:
`record_thumb` + `collect_thumbs` over the bound `OutcomeStore`, wired by
`engine._wire_outcome_store`. Pinning a test to dead code would have
hidden the defect the issue names, so the code was removed instead.

## 3. Develop sync

Merged `origin/develop` (`4019249e8`, the job's stated base) into
`auto-337` (commit `fb1bc7f84`). It auto-resolved; the two develop
commits (`8edb51fb9`, `4019249e8`) touch builders/pipeline, design
`__init__`, two root suites, and remove rows from the quality ledgers.
`git diff --numstat origin/develop -- quality/` is empty after the merge —
no row silently lost or duplicated; the vulture ledger is a multiset and
nothing was passed through `set()`.

## 4. Validation executed at the final head `fb1bc7f84`

- `uv run ruff check .` → **All checks passed!**
- `uv run ruff format --check .` → **3530 files already formatted**
- `uv run pytest packages/hive-conductor/backend/tests --timeout=30 -q`
  → **4084 passed, 28 skipped** (full hive producer, under coverage).
- Diff-coverage gate with CI's exact script, both candidate bases:
  - `check-diff-coverage.py coverage.xml --base 09d56b6a0` (the observed
    PR base, with the full hive + maistro-core + maistro-design coverage
    present) → **ok: every measured file this change touches is at or
    above 90% lines / 80% branch arcs**.
  - `check-diff-coverage.py coverage.xml --base origin/develop`
    (`4019249e8`, the job's stated base) → **ok**.
  - `feedback_service.py` is no longer named; the function's lines are
    gone from the diff.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **1256 reviewed
  identities -> 1256 findings, exit 0** (no ledger amendment needed; the
  removed function was never a vulture finding — `packages/hive-conductor`
  is not under `packages/*/src`).
- `uv run python scripts/check-ratchet-provenance.py` → **OK** (358
  contract-marker gaps, 1 enumeration gap, 0 lifecycle violations; no
  candidate-approved expansion).
- `uv run python scripts/check-shipped-surface-truth.py` → **complete**.
- `uv run python scripts/check-suite-inventory.py` (all 21 suites) →
  **ok: 21 suite(s) match the recorded inventory, 34712 unique identities,
  0 duplicates**; hive backend suite alone → **ok at 4112**.
- Issue #337 acceptance battery (dag-run history durability, durable node
  metrics, node metrics measured, goal inspection, profile durability,
  dag-run scope, optimizer, hill-climb loop, feedback route, thumbs
  protocol) → **363 passed**.

## Not touched / residuals

- No production code added: the repair is one deletion plus the develop
  sync. No test count changed, so no inventory note is required.
- The publish-set floor (`coverage report --fail-under=87`) is untouched by
  this change; the removed file is in `packages/hive-conductor/backend`,
  outside the publish set.
