---
inventory-delta:
  packages/maistro-core/tests: +0
---

# Issue 41 CI repair (round 9): radon ratchet, renewal-poll deflake, ac-state bank

Three CI failures at head 17fda499 (PR #1325) reproduced and repaired at the
develop-synced head; no test cases added or removed, so the collected-case
count is unchanged (`check-suite-inventory.py --suite packages/maistro-core/tests`
-> ok, 11041, re-executed after the edit).

## Quality gate — radon CC ratchet

`scripts/check-radon-baseline.py` failed with two unbaselined C blocks the
#1176 claim loop introduced: `tasks/idempotency.py:516 claim -> C (11)` and
`tasks/queue.py:277 _submit_idempotent -> C (12)`. Both were decomposed along
their own seams rather than banked as debt:

- `_ClaimFlow.claim`'s read-side assessment moved to `_ClaimFlow
  ._classify_claim` (B, 5) — mismatch raises, replayed/pending/ambiguous
  return, `takeover` returns None so the caller proceeds to the write-side
  guard. `claim` is now B (8).
- `TaskQueue._submit_idempotent`'s outcome-to-response step moved to
  `TaskQueue._claim_outcome_response` (B, 6) — Replayed/Ambiguous/Claimed
  answered there, everything else returns None for the bounded pending wait.
  `_submit_idempotent` is now B (8).

Ratchet re-executed green: 68 reviewed -> 68, zero new/regressed/stale. The
in-memory + durable idempotency suites re-ran green (tasks suites 333 passed
1 skipped; durable legs live on pgvector/pg18).

## coverage (PostgreSQL) — renewal-poll starvation flake

`test_parked_run_resume.py::test_a_resumed_schedule_attempt_is_leased_and_
reclaimed_after_worker_death[sqlite]` failed on CI with "a live resumed
Attempt was not renewed by the heartbeat" — the renewal poll's wall-clock
deadline (15 s) expired while a starved coverage runner gave neither the poll
nor the heartbeat coroutine a loop turn (the failure mode the test's own
comment documents from an earlier CI flake). The budget is now 150 completed
poll iterations: each completed iteration proves the loop was scheduled, and
once it is, the heartbeat's lapsed timer (ttl/3) fires within a few
iterations. Mutation-checked: with `renew_lease` stubbed to a no-op the test
fails in ~10 s instead of hanging; unmutated, all 42 collected cases in the
file pass. The full CI battery re-ran green on a fresh pgvector/pg18:
persistence + container_postgres + events + runs + graph + projects +
workspaces + scheduling = 4174 passed, 7 skipped (CI had 4173 + 1 failed).

## Quality gate — ac-state unbanked improvement

Running the previously-unreached later steps of the Quality gate surfaced
`check-ac-state.py --run-tests --ratchet --mandate` failing with
"unbanked improvement: design_coverage 38.0924, floor still says 33.9095" —
this branch's proven criteria raised design coverage and the gate requires
banking the improvement. Banked via the gate's own `--bank` on a fresh
database (AC tests are not idempotent against dirty DB state: a second
consecutive run measures 33.607; CI always measures a fresh first run, which
is deterministically 38.0924). `quality/ac-state-notes/auto-41.json` records
the measurement; ratchet + mandate then re-executed green (10 debt counters
on their ceilings, progress counter exactly on the banked floor).

## gates-ran

"Required execution evidence is missing or non-executed" was the downstream
symptom of the Quality gate aborting at radon; with every Quality gate step
now locally green (ruff, radon, bump_version, release consistency, doc links,
enumerations, vendored benchmarks, xenon, vulture, reachability, credential
authority, wiring reads, agent store writes, contract markers, convergence
matrix, dispositions, security/image/backlog inventories, alembic chain,
ac-state, mypy --strict, pyright 20<=21, formal/ 663 passed, lifecycles,
model egress, fitness 7 passed, interrogate floors) the evidence set is
complete.
