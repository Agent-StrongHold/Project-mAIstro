---
inventory-delta:
  packages/maistro-core/tests: +5
---
# cursor-m1-b-p4b-reconciler-recovered-disposition-8551-2e2c

#232 P4b reconciler provenance: five new cases covering unknown CANCELLED
refusal (with/without caller RECOVERED), transitional unknown+REQUESTED
terminalize, conflicting caller cause, typed RECOVERED disposition
delegation, and typed REQUESTED terminalize. Spine rename of the old
"recovery is the default" case is net-zero.

## Verification evidence (repair round, head 70b1d7f7dab0)

Fail-before/pass-after for the two acceptance-named provenance tests:
re-introducing the pre-P4b implicit `CancellationCause.RECOVERED` fallback
(`cause = persisted.cancellation_cause or cancellation`) in
`_reconcile_cancelled` fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered` and
`test_conflicting_caller_cause_refuses` (DID NOT RAISE RunIntegrityError);
HEAD content restored byte-identical (sha256 5200bb08b7d73a63) and the file
passes again. Gates re-run at head: targeted battery 441 passed;
`packages/maistro-core/tests/runs` 1614 passed; `graph/durable_runs` 846
passed; ruff check + format clean; CI-exact vulture ledger exit 0 (1229
identities). `pr-base` failure at head is the ADR-095 stacked-PR expectation:
`check-pr-base.py --base cursor/m1-b-p4a-recovered-disposition-8551` exits 1
with the retarget instruction while `--base develop` passes, so the gate
resolves at merge-time retarget and needs no code change.

## Verification evidence (independent verifier round, head 018e88885cb9)

All claims above re-proven independently, not assumed: targeted P4b battery
(provenance + disposition + orphan + pg statement + canvas suites) 98 passed,
0 skipped, on a fresh throwaway PostgreSQL 18 container (alembic head 068);
full `tests/runs` + `tests/graph/durable_runs` 2933 passed, 4 skipped,
4 xfailed on the same server. Fail-before re-proven with two independent
mutations of `_reconcile_cancelled`: (1) replacing the null-cause raise with
the pre-P4b `RECOVERED` fallback fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered`
(RecoveredDispositionRefused instead of RunIntegrityError); (2) additionally
disabling the conflict check fails exactly
`test_conflicting_caller_cause_refuses` as well. An ineffective mutation
(reassigning `cause` while keeping the raise) passes all five tests —
the tests pin the refusal itself, not a shadow of it. HEAD content restored
byte-identical both times (sha256 5200bb08b7d73a63, `git diff` empty).
Reachability of the transitional null-cause+REQUESTED branch confirmed in
production: `execution.py::_terminalize` writes CANCELLED without a stamp and
`_reconcile(..., cancellation=REQUESTED)` supplies the caller cause
(execution.py:531, 684). CI-exact gates re-run green: vulture ledger
(1229=1229, exit 0), radon (126=126), reachability (exit 0), execution
lifecycles (19=19), image pins, promotion surface, full suite inventory
(21/21), mypy strict (958 files), ruff check + format. Captured check-runs at
this exact head: every completed run success except `pr-base` (failure) —
the documented ADR-095 stacked-base expectation, proven locally
(`check-pr-base.py` stacked base exit 1, `--base develop` exit 0).

## Verification evidence (independent verifier round, head ccf3fcec09fa)

Re-proven at the current review head, not assumed from earlier rounds:
targeted P4b battery (canvas canonical_execution + durable execution_store
+ pg statement + provenance + orphan + disposition + recovery events/evidence
+ spine, CI-exact argv) 414 passed, 140 skipped without services; RSI kernel
research 27 passed; `ruff check` + `ruff format --check` clean; suite
inventory gates green for hive-backend, canvas, core, and rsi suites.
Live-database legs proven on a fresh local pgvector/pgvector:pg18 container
(alembic head 068): the five disposition/provenance/orphan/spine modules 454
passed with zero skips, and the full `tests/runs` + `tests/graph/durable_runs`
battery 2933 passed, 4 skipped, 4 xfailed - matching the recorded prior
round. Fail-before re-proven at this head: reintroducing the pre-P4b
`persisted.cancellation_cause or cancellation` fallback fails exactly
test_unknown_cancelled_refuses_even_with_caller_recovered
(RecoveredDispositionRefused instead of the required RunIntegrityError
"unknown cancellation_cause"); HEAD restored byte-identical (sha256
5200bb08b7d73a63..., `git status` empty). Sweep replay contract re-run green
(test_the_sweep_survives_an_attempt_it_cannot_reconcile), and both Container
sweep halves catch RecoveredDispositionRefused alongside RunIntegrityError
(container.py:1436, container.py:1501). pr-base re-proven as the ADR-095
stacked-base expectation: `check-pr-base.py --base
cursor/m1-b-p4a-recovered-disposition-8551` exits 1 with the retarget
instruction while `--base develop` exits 0. Hosted check-runs captured at
exactly this head sha: every completed run success except pr-base; still
in progress at capture time were docker-build, coverage (no services), test,
and integration-scope.

## Verification evidence (develop-sync repair round, head e4e73977cd)

Resolved the preserved develop-sync conflict (merge of 228dec753f then
origin/develop 8f4806bef3, merge-base now == origin/develop tip). RSI
kernel-research counts resolved as the union of both sides (12 translatable
/ 24 total / 50%), confirmed by the suite itself: 27 passed. Gates re-run
at head: `ruff check` + `ruff format --check` clean; mypy strict 1127 files
clean; CI-exact vulture ledger exit 0 (1229 identities, unclassified 0);
radon 126=126; promotion surface ok; reachability ok; execution lifecycles
19=19; image pins ok; `check-suite-inventory.py` 21/21 suites match (35848
unique identities). Runs battery with live PostgreSQL 18 (Docker,
alembic-upgraded): full `tests/runs` + `tests/graph/durable_runs` 2933
passed, 4 skipped, 4 xfailed. Fail-before claim re-proven independently:
re-introducing the pre-P4b `persisted.cancellation_cause or cancellation`
fallback (without the conflict check) fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered` and
`test_conflicting_caller_cause_refuses`; HEAD restored byte-identical
(sha256 5200bb08b7d73a63...) and green again.

## Verification evidence (post-merge verifier round, head 7f1cbf68c45f)

Re-proven at the current review head (merge of develop tip 0d7bdd0a866a;
merge-base == origin/develop tip, so the branch is develop-current).
`reconciliation.py` is byte-identical to the content every earlier round
proved (sha256 5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79),
so the P4b authority/refusal logic survived all develop merges unchanged.
Acceptance battery re-executed, not assumed: fresh pgvector:pg18 container,
alembic head 068; P4b suites (provenance + disposition + orphan + pg
statement + durable execution_store) 86 passed with the postgres legs
actually running (`test_unknown_cause_refuses[postgres]`,
`test_parks_node_and_run[postgres]` PASSED individually); canvas
canonical_execution + spine conformance + recovery events/evidence 468
passed; full `tests/runs` + `tests/graph/durable_runs` 2933 passed,
4 skipped, 4 xfailed — identical counts to the two prior live-PG rounds.
Fail-before re-proven at this head with the same mutation: the pre-P4b
`cause = persisted.cancellation_cause or cancellation` fallback fails
exactly `test_unknown_cancelled_refuses_even_with_caller_recovered` and
`test_conflicting_caller_cause_refuses` (2 failed / 3 passed), HEAD
restored byte-identical (sha256 5200bb08..., `git status` empty), green
again. CI-exact gates at this head: vulture ledger exit 0 (1222 == 1222
against base 0d7bdd0a866a); `check-suite-inventory.py` 21/21 suites match
(35881 unique identities, +33 from develop's own changes); `ruff check` +
`ruff format --check` clean; RSI kernel research 27 passed;
`test_the_sweep_survives_an_attempt_it_cannot_reconcile` green with both
Container sweep halves catching `RecoveredDispositionRefused`
(container.py:1436, container.py:1501) and the Graph tick isolating
ValueError candidates (recovery.py:391,538). pr-base re-proven as the
ADR-095 stacked-base expectation: `check-pr-base.py --base
cursor/m1-b-p4a-recovered-disposition-8551` fails with the retarget
instruction while `--base develop` passes. Hosted check-runs captured at
exactly this head sha: every completed run success — including
coverage (no services), coverage (PostgreSQL), coverage (MinIO),
exact-debt-ledger, Mutation gate, Mypy strict, and all Quality/SAST jobs —
except pr-base; at capture time `test` and the publish-set coverage queue
were still running. Hosted Codex P1 (untyped Canvas CANCELLED before
parking) confirmed remediated in-branch: `_settle_abandoned_attempt`
reclaims via the authorized P2a writer (CANCELLED+RECOVERED) before
disposition, with race-refusal fallback tests
(`test_race_or_require_terminal_resolves_or_refuses`,
`test_reclaim_recovered_attempt_falls_back_when_reclaim_raises_or_returns_none`)
plus the two P4b provenance-suite canvas-adjacent cases in
test_canonical_execution.py.
