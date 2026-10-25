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
