---
inventory-delta:
  packages/maistro-core/tests: +21
---
# CR1373 recovery evidence repairs

External discovery regressions reproduce the fixed-prefix defect at limit=1
for both WAITING and PAUSED completions (both failed before the repair). A
bounded multi-tick case covers advancing beyond the inspection ceiling, a
provider failure without lifecycle mutation, wraparound and eventual delivery.
The registered-DAG consumer retains the same caller-owned scan continuation
used by the existing queued and due recovery seams. The cursor grants no
execution authority; external completions still go through the canonical store.

Accepted ADR-082826-d9f5 and ADR-083026-6e2a retain RunStore plus Graph continuation
as the sole recovery record. No scheduler, lifecycle store or Event authority
is introduced. Broader parent acceptance and child closure are not claimed.

Canonical store receipt tests add six collected cases across memory, SQLite,
and PostgreSQL-continuation fixtures. Foreign task/handle and missing receipts
are rejected without changing the record; matching delivery and exact replay
remain supported. The task case enters through Container's real completion
bridge. Existing synthetic harness fixtures now persist and deliver a matching
handle rather than exploiting missing identity checks.

Nine cases cover canonical terminal-checkpoint recovery Events: immediate
publication, failed append followed by fresh-store bounded sweep/replay behind
older terminal history, and crash after intent but before lifecycle commit.
The canonical Event store assigns the Workspace sequence and deduplicates replay.
These prove terminal Graph repair publication (the same protocol is used by
terminal HITL mirrors), not every nonterminal reconciliation branch. Three more cases cover canonical status discovery across
parked Runs with no continuation (empty assembled pages must advance).

PostgreSQL cross-store tests were also run against an isolated migrated scratch
database: 74 passed, with no skips. This fixture uses PostgreSQL continuation
persistence and an in-memory Run spine; it is not proof of full PostgreSQL Run
persistence or OS-process-kill durability. SQLite cases do exercise the durable
Run spine; store reopen and injected crashes are not OS kill proof. Inventory: 3 discovery + 6 receipt + 6 append/replay + 3 precommit crash +
3 canonical discovery = 21 collected cases.

## Executed validation and remaining acceptance

Local implementation commit: `5e1d1f7c0` (handoff only; no integration approval).
Logs are under `/home/dev/maistro/jobs/2117197731294996a765877980beb744/`.

- `uv sync --locked --extra dev` passed.
- Ruff check and format check passed repository-wide.
- Strict configured-package mypy passed (942 source files).
- Broad Graph/Run/A2A pytest passed: 3,955 passed, 510 skipped, 4 xfailed.
- Coverage rerun adding Container wiring: 4,012 passed, 510 skipped,
  4 xfailed; six aiosqlite thread-shutdown warnings were visible.
- Hive DAG/registered-DAG recovery: 27 passed, including the coverage rerun.
- Isolated migrated PostgreSQL cross-store suite: 74 passed, zero skips.
  Its first run caught an undated-orphan cursor regression introduced by the
  new sweep; exhaustion/reset now avoids passing an empty timestamp to PG.
- Exact CI-shaped Vulture, Radon, lifecycle, convergence, reachability and
  reachability-disposition checks passed. No quality ledger/grant was changed.
  Radon initially rejected the new terminal branch; sharing the actual
  intent/commit/publish protocol across both terminal mirrors fixed it.
- Both suite inventories passed (Core 18,019; Hive 4,095).
- `check-diff-coverage.py coverage.xml --base 09d56b6a0b3553b0d61dc50fceeeb7547b6893c9`
  passed: all 13 measured changed source files meet 90% lines / 80% branch arcs.
  No gate thresholds or coverage exemptions changed.

Parent #62 acceptance is not declared complete:

| Criterion | Evidence / limitation |
| --- | --- |
| Process restart recovery | SQLite close/reopen recovery tests passed; actual OS-process-kill proof UNVERIFIED. |
| Discoverable timed waits | Due-index, harness-timer and registered-DAG tests passed; all production admission classes UNVERIFIED. |
| Every parked reason has a reachable waker | Registry and existing behavioral waker suites passed; complete production-class matrix UNVERIFIED. |
| Remote completion/deadline cannot stay invisible | New fair polling and real canonical receipt correlation regressions passed; all adapter/deadline combinations UNVERIFIED. |
| Each supported class consumed in production | Registered-DAG recovery exercised; complete producer/admission matrix UNVERIFIED. |
| Fencing and chronological Attempts | Existing lease/refusal/restart/Attempt suites passed; no execution authority changed. |
| Compatible, canonical-ID-bound checkpoints and purge | Continuation conformance, canonical identity, time-travel and purge tests passed; cross-release executable compatibility UNVERIFIED. |
| Partial-write idempotence | Cross-store crash/reopen and repeated-reconciliation tests passed, including real PG continuation storage. |
| Stranded RUNNING windows | Existing frontier, claim, terminal-continuation and cross-store tests passed. |
| Canonical recovery Events | Terminal Graph repair, failed append/replay and precommit crash proven; nonterminal reconciliation Event coverage UNVERIFIED. |
| Retired stores cannot regain authority | Existing checkpoint-authority, legacy guard/archive tests passed. |
| Children #837/#1151/#1192 accepted before closure | UNVERIFIED; no issue/PR mutations or closure actions. |

The scratch database `cr1373_repair_21171977` is retained on the already-running
`cr1373-ac-pg` service. No existing database was truncated by this validation.
