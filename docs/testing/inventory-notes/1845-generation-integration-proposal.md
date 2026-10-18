---
inventory-delta:
  packages/maistro-core/tests: +461
---
# 1845-generation-integration-proposal

## Fresh reconstruction and collected change

Reconstruction/test base: `f277bae570d132d6e7086301112cf9bcb90ed304`.
Publication refresh: `2f56be40ad241262b0384ab0b97834ebd37fe4d7`; preserves
landed #1993 Sentinel configuration without admission-file overlap.
Runtime checkpoint: `22c1592e22d6baa1f8b583ebae3c6ca04d367470`.
This note and the proposal document belong to the same review branch; the final
publication SHA is recorded in its PR. No prior workspace's test results are
reused.

The core suite grows from 16,426 to 16,887 collected nodes (+461): immutable
identity, pure classifier, row codec, task adapter, transactional coordinator,
composed queue/runner, and eight explicit live-PostgreSQL cases. No existing
suite or test was removed; the leaf's inactive-import assertion is replaced by
an integration assertion that the actual coordinator consumes the classifier
while the legacy store retains its separate protocol. No copied-test duplicates
were found by inventory collection.

## Executed locally on 2026-10-18

- Coordinator/queue: 74 passed. This composes actual canonical Run-store methods
  with a transactional transport double; it is not real database durability.
- Tasks + runs + container wiring/PostgreSQL/SQLite fixture suites under branch
  coverage: 2,269 passed, 324 skipped. The unchanged diff-coverage checker passes
  every changed source file at 90% lines / 80% branch arcs.
- Independent review: 138 coordinator/queue/adapter/runner/cancellation tests
  passed; 342 identity/classifier/codec tests passed, with three SQL cases skipped.
- Eight new live-PG cases collect and explicitly skip with no local DSN. Setting
  `MAISTRO_REQUIRE_PG_LEGS=1` fails setup rather than allowing a false green skip.
  Hosted PostgreSQL 17/18 results are still required at the exact final head.
- Ruff check/format pass on all changed Python files; focused mypy passes eight
  changed source files. Bandit passes CI's Medium+ / medium-confidence threshold.
- Against explicit trusted base f277bae: Vulture remains 1,322 reviewed
  identities; Radon remains 137 C-or-worse blocks. Reachability remains 169
  unreachable modules and all dispositions pass. No quality ledger or grant
  changed. Promotion surface passes.
- The broad core run has 32 DNS-dependent outbound/browser/skill failures in this
  restricted environment. All 32 were rerun on untouched f277bae and reproduce.
  The final full-core rerun is reported separately in the PR when it completes;
  this note does not claim a clean full-suite run.

Commands use the locked development dependencies. The coverage command was:

```sh
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 coverage run --branch \
  --source=packages/maistro-core/src/maistro -m pytest \
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runs \
  packages/maistro-core/tests/test_container_wiring.py \
  packages/maistro-core/tests/test_container_postgres.py \
  packages/maistro-core/tests/test_container_sqlite_backend.py -q --tb=short
coverage xml
python scripts/check-diff-coverage.py coverage.xml \
  --base f277bae570d132d6e7086301112cf9bcb90ed304
```

Environment-only proxy variables were unset for local fixture tests; no runtime
network guard or test assertion was disabled. A missing SOCKS extra otherwise
prevented an unrelated HTTP-client construction test before it exercised code.

## Regression evidence

Fail-before/pass-after evidence was captured for:

- legacy completed task_id/run_id with absent/NULL forward receipt_id, and
  contradictory forward identity;
- nonfinite original task evidence being erased by ordinary serialization;
- raw preparation connection failure deleting the active generation;
- optional acknowledgement timing out an already committed submission;
- cancellation during actual LaneGate wait and before a dispatcher worker's
  first coroutine step stranding its same-queue dispatch hint.

Additional deterministic tests cover the started-worker callback preserving a
replacement hint, raw COMMIT connection-loss resolution, original provenance,
stale fences, inclusive expiry, capacity rollback and cancellation retention.
Isolated mutation-negative checks show that disabling provenance validation or
using cache-only dispatch suppression makes the respective regression fail.

These tests do not prove a live process kill, real lost COMMIT bytes, cross-replica
physical-effect uniqueness or an accepted operational cutover. See the blocking
checklist in `docs/implementation/1845-generation-integration-proposal.md`.
