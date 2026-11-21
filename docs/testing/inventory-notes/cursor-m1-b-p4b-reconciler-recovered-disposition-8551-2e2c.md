---
inventory-delta:
  packages/maistro-core/tests: +9
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

## Verification evidence (independent verifier round, head 92b08598a75e)

Re-proven at the current review head (parent 7f1cbf68c45f + this docs-only
commit; `reconciliation.py` sha256 5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79
— byte-identical to every proven round). Acceptance battery executed fresh:
targeted P4b suites (provenance + disposition + orphan + durable
execution_store) 71 passed / 10 skipped without services; canvas
canonical_execution + spine + recovery events/evidence 338 passed / 130
service-skips; sweep/replay survival 16 passed; marker-docs parametrization
collects `test_axis_markers_document_only_their_registered_values[timeout]`
(tests/: +1, skipping as documented). Live-database leg on a throwaway
pgvector:pg18 container (alembic head 068): the same five P4b suites 86
passed with zero skips, and the full `tests/runs` +
`tests/graph/durable_runs` battery 2933 passed, 4 skipped, 4 xfailed —
identical counts to the three prior live-PG rounds; container removed after.
Fail-before re-proven with two independent mutations: (1) pre-P4b
`persisted.cancellation_cause or cancellation` fallback alone fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered`
(RecoveredDispositionRefused instead of the required RunIntegrityError);
combined with disabling the conflict check it fails that test AND
`test_conflicting_caller_cause_refuses` (2 failed / 3 passed); (2) reverting
`attempt_executor._reconcile_orphaned_attempts` to generic
`transition_attempt(CANCELLED)` fails 3 test_recovery_disposition cases
(`test_resume_still_steals_an_expired_recovery_claim`,
`test_repeated_orphan_reconciliation_is_idempotent`,
`test_mid_attempt_restart_on_sqlite_produces_the_documented_disposition`) —
all binding the executor to the dedicated RECOVERED-stamping writer. Both
mutations restored byte-identical (sha256 5200bb08… / 82e07fbc…, `git
diff`/`git status` empty) and green again. CI-exact gates at this head:
vulture ledger exit 0 (1222 == 1222 against base 0d7bdd0a866a);
`check-suite-inventory.py` 21/21 suites (35881 unique identities); ruff
check + format clean. pr-base re-proven as the ADR-095 stacked-base
expectation with the workflow's exact argv:
`check-pr-base.py --base cursor/m1-b-p4a-recovered-disposition-8551` exits 1
with the retarget-to-develop instruction, `--base develop` exits 0. Hosted
check-runs queried live at exactly this head sha: 70 success (incl.
exact-debt-ledger, Mutation gate, Mypy strict, postgres pg17/pg18,
Coverage-queue precursors), pr-base the only completed failure, and 9 heavy
jobs still in flight at capture (docker-build, hive-conductor e2e legs,
coverage (PostgreSQL)/(no services), test, integration-scope, Container
scan, Quality gate) — the branch delta vs the verified parent is this single
docs commit, so those legs are content-equivalent to the parent-head runs
where every completed coverage job was success.

## Verification evidence (independent verifier round, head f19ebd890d2c35)

Re-proven at the exact review head (delta vs the verified parent 7f1cbf68c45f
is the f19ebd890d docs commit alone; `reconciliation.py` sha256
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79, unchanged).
The prior round's launch block — "Hosted PR snapshot incomplete or not the
review head" — is resolved: the dispatch snapshot of PR #2425 is complete
(81 check runs captured at 2026-11-21T10:54Z) and the hosted PR head sha
equals f19ebd890d2c35659fbbda5b7e6ba08439da81f2, the local review head.
Acceptance battery executed fresh at this head: P4b suites (provenance +
disposition + orphan + pg disposition + durable execution_store) 76 passed /
10 skipped; canvas canonical_execution + recovery events/evidence + spine +
rsi-marker battery 365 passed / 130 service-skips. Fail-before re-proven with
the pre-P4b `persisted.cancellation_cause or cancellation` fallback in
`_reconcile_cancelled`: fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered`
(RecoveredDispositionRefused instead of the required RunIntegrityError,
1 failed / 4 passed); restored byte-identical (sha256 verified above, `git
status` empty) and green again. CI-exact gates at this head: vulture ledger
exit 0 (1222 == 1222 against base 0d7bdd0a866a);
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (18771
unique identities; driver runs also ok for hive-conductor backend,
maistro-canvas, maistro-rsi); ruff check + format clean (driver logs).
pr-base re-proven as the ADR-095 stacked-base expectation with the ci.yml
exact argv (`--base "$PR_BASE" --labels "$PR_LABELS"`):
`check-pr-base.py --base cursor/m1-b-p4a-recovered-disposition-8551` exits 1
with the retarget-to-develop instruction, `--base develop` exits 0. Hosted
check-runs from the complete snapshot at this head sha: 78 success — now
including coverage (no services), coverage (PostgreSQL), coverage (MinIO),
exact-debt-ledger, Mutation gate, Mypy strict, postgres pg17/pg18 and the
Quality/SAST families — with pr-base the only completed failure (the
documented stacked-flow expectation) and only 2 jobs still in flight at
capture (publish-set Coverage gate, test).

## Verification evidence (repair round, head 3e5f17bb9bc40b8d)

The round's prior block — "recovery budget exhausted: launch/preflight:
Hosted PR snapshot incomplete or not the review head" — is resolved: the
develop-sync merges (ef000b0fff, 3e5f17bb9bc4, base 527cff843735) landed and
this dispatch's snapshot of PR #2425 is complete (81 check runs captured
2026-11-21T11:25Z) with the hosted PR head sha equal to 3e5f17bb9bc40b8dd061
e3e72988441e68094bcb, the local review head. The delta vs the verified parent
f19ebd890d2c35 contains zero changes in packages/maistro-core, maistro-canvas
and maistro-rsi; `reconciliation.py` keeps sha256
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79 — the P4b
code under review is byte-identical across all proven rounds. Acceptance
battery executed fresh at this head: P4b focused suites (provenance +
disposition + leaseless orphan + pg disposition + recovery events) 50 passed
/ 10 skipped; canvas canonical_execution + durable execution store + spine
conformance + recovery evidence pack 364 passed / 130 service-skips; driver
battery (check-3) 441 passed / 140 skipped at the same head. Fail-before
re-proven: re-introducing the pre-P4b `persisted.cancellation_cause or
cancellation` fallback in `_reconcile_cancelled` fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered`
(RecoveredDispositionRefused instead of the required RunIntegrityError, 1
failed / 4 passed); restored byte-identical from a backup copy (sha256
verified above, `git status` empty) and green again. CI-exact gates at this
head: `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exit 0 (1222 == 1222 against base 527cff843735); ruff
check + format clean (driver check-1/check-2); `check-suite-inventory.py` ok
for maistro-core (18771), hive-conductor backend, maistro-canvas,
maistro-rsi (driver check-5..8). pr-base re-proven with the ci.yml exact argv
(`--base "$PR_BASE" --labels "$PR_LABELS"`): a stacked cursor/ base exits 1
with the retarget-to-develop instruction while `--base develop` exits 0 — the
ADR-095 stacked-flow expectation. Hosted check-runs from the complete
snapshot at exactly this head sha: 77 success — including coverage (no
services), coverage (PostgreSQL), coverage (MinIO), exact-debt-ledger,
Mutation gate, Mypy strict, postgres (pg17)/(pg18) and the full Quality/SAST
families — with pr-base the only completed failure (documented expectation);
2 in-flight and 1 queued heavy jobs at capture are content-equivalent to the
parent-head runs because the branch delta vs the verified parent is
develop-sync dependency/workflow content only.

## Verification evidence (repair round, head e697856c3be72939)

The round's prior block — "launch/preflight: Hosted PR snapshot incomplete or
not the review head" — is resolved: this dispatch's snapshot of PR #2425
carries head sha e697856c3be72939625f0cef0c42bcf4c0b71a23, equal to the local
review HEAD (79 check runs captured 2026-11-21T12:00Z), and
`complete_for_scope` is true. The delta vs the verified parent 9f8fa5ebffdb5
is the develop-sync merge of 884408b066 (hive-conductor legacy Dashboard
deletion, #2274) plus develop's own quality baselines — `git diff --stat`
9f8fa5ebff..e697856c3be7 touches no file under packages/maistro-core,
maistro-canvas or maistro-rsi, and `reconciliation.py` keeps sha256
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79 — so the P4b
code under review is byte-identical across all proven rounds. Acceptance
battery executed fresh (not assumed) at exactly this head: P4b focused suites
(provenance + disposition + leaseless orphan + pg statement-shape + durable
execution store + spine conformance + recovery events/evidence + canvas
canonical execution) 414 passed / 140 skipped without services. Live-database
leg re-proven on a throwaway pgvector:pg18 container (docker service on port
5433, `alembic upgrade head` to 068, MAISTRO_TEST_PG_DSN set): the five P4b
suites 50 passed with zero skips (the 10 service-skips become green postgres
spine legs), and the wider battery (durable execution store + spine
conformance + recovery events/evidence + canvas canonical execution) 504
passed with zero skips; container removed after. Fail-before re-proven with
the pre-P4b `persisted.cancellation_cause or cancellation` fallback in
`_reconcile_cancelled`: fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered`
(RecoveredDispositionRefused instead of the required RunIntegrityError,
1 failed / 4 passed); restored byte-identical from a backup copy (sha256
verified above, `git status` empty) and green again (5/5). CI-exact gates at
this head: `check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` exit 0 (1222 == 1222 against base 884408b066f1,
the new merge base); ruff check + format clean; suite inventory ok ×4 (driver
check-5..8: hive-conductor backend 4273, maistro-canvas 633, maistro-core
18771, maistro-rsi 1797 — the merged develop content included). pr-base
re-proven with the ci.yml exact argv (`--base "$PR_BASE" --labels
"$PR_LABELS"`): a stacked cursor/ base exits 1 with the retarget-to-develop
instruction while `--base develop` exits 0 — the ADR-095 stacked-flow
expectation, matching the hosted snapshot where pr-base is the only completed
failure and the coverage/postgres/test families were still in flight (None)
at capture, content-equivalent to the parent-head runs where every completed
coverage job was success.

## Verification evidence (independent verifier round, head bdd57cb573cbc53)

The prior block — "recovery budget exhausted: launch/preflight: Hosted PR
snapshot incomplete or not the review head" — is resolved: the dispatch
snapshot of PR #2425 carries head sha bdd57cb573cbc53d235a3632d772fac4862207c6,
equal to the local review HEAD (79 check runs captured 2026-11-21T12:36Z,
`complete_for_scope` true), and 66 hosted jobs are success with pr-base the
only completed failure (the documented ADR-095 stacked expectation; 12 still
in flight at capture). The delta vs the verified parent ef2f8a2ab22022 is the
develop-sync merge of 971e536838ca (collaboration CONNECT park, #2323):
`git diff --stat ef2f8a2ab22022..bdd57cb573cbc53` touches exactly one file
(`packages/maistro-core/tests/test_collaboration_park_2323.py`, +27, develop's
own content) and no P4b source — `reconciliation.py` keeps sha256
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79 — so every
claim proven at parent heads transfers byte-identically.

Everything below was re-executed fresh at exactly this head, not assumed:
focused P4b battery (provenance + disposition + leaseless orphan + pg
statement-shape + durable execution store + spine conformance + recovery
events/evidence + canvas canonical execution + rsi kernel suite) 441 passed /
140 skipped without services — the 140 skips are precisely the service-gated
legs. Live-database leg on a throwaway pgvector:pg18 container (port 5433,
`alembic upgrade head` to 068, MAISTRO_TEST_PG_DSN set): the same battery
581 passed with zero skips, proving the PG worker-death safety leg at this
head directly; container removed after. CI-exact vulture ledger
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exit 0 (1222 == 1222 against base 971e536838ca);
ruff check + format clean; suite inventory ok ×4 (driver check-5..8:
hive-conductor backend 4273, maistro-canvas 633, maistro-core 18772 — +1
from the merged park test — maistro-rsi 1797); `check-doc-links.py` 0
broken. pr-base re-proven with the ci.yml exact argv (`--base "$PR_BASE"
--labels "$PR_LABELS"`): a stacked cursor/ base exits 1 with the
retarget-to-develop instruction while `--base develop` exits 0. Fail-before
re-proven at this exact head: reintroducing the pre-P4b
`persisted.cancellation_cause or cancellation` fallback in
`_reconcile_cancelled` fails exactly
test_unknown_cancelled_refuses_even_with_caller_recovered
(RecoveredDispositionRefused instead of the required RunIntegrityError,
1 failed / 4 passed); restored byte-identical (sha256 verified above,
`git status` empty) and green again (5/5).

## Verification evidence (verifier+writer round, head ba88f29b1cc44c0d)

The recurring launch block — "Hosted PR snapshot incomplete or not the review
head" — is resolved: this dispatch's snapshot of PR #2425 carries head sha
ba88f29b1cc44c0d96dff756b6d9e1b37f1fefde, equal to the local review HEAD
(80 check runs captured 2026-11-21T13:31Z, `complete_for_scope` true), and
the hosted snapshot shows every completed job success — including
coverage (no services), coverage (PostgreSQL), coverage (MinIO), Coverage
gate, exact-debt-ledger, Quality / Vulture, Mutation gate, Mypy strict,
postgres (pg17)/(pg18) and the full Quality/SAST families — with pr-base the
only completed failure (the documented ADR-095 stacked expectation). The
delta vs the verified parent bdd57cb573cbc53 is this round's docs commit
alone; `reconciliation.py` keeps sha256
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79 — the P4b
code under review is byte-identical across all proven rounds.

Everything below was re-executed fresh at exactly this head, not assumed:
driver deterministic checks green (check-0..8: uv sync, `ruff check`,
`ruff format --check` 3610 files, focused battery 441 passed / 140 skipped,
hive-conductor audit pagination 32 passed, suite inventory ok ×4:
hive-conductor backend 4273, maistro-canvas 633, maistro-core 18772,
maistro-rsi 1797). Fail-before re-proven with the pre-P4b
`persisted.cancellation_cause or cancellation` fallback in
`_reconcile_cancelled`: fails exactly
test_unknown_cancelled_refuses_even_with_caller_recovered
(RecoveredDispositionRefused instead of the required RunIntegrityError,
1 failed / 4 passed); restored byte-identical from a backup copy (sha256
verified above, `git status` empty) and green again (5/5).

Live-database leg on a throwaway pgvector:pg18 container (port 5433,
`DATABASE_URL` for alembic, `alembic upgrade head` to 068,
MAISTRO_TEST_PG_DSN as a raw asyncpg `postgresql://` DSN — the
`postgresql+asyncpg://` scheme is rejected by asyncpg itself): the P4b
battery (canvas canonical execution + durable execution store + pg
disposition statement + provenance + leaseless orphan + disposition +
recovery events/evidence + spine conformance) 554 passed with zero skips —
all 140 service-gated legs green, proving the PG worker-death safety leg at
this head directly; named legs `test_parks_node_and_run[postgres]` and the
pg disposition suite 6 passed individually; container removed after.
Sweep-replay contract re-run green
(test_the_sweep_survives_an_attempt_it_cannot_reconcile). CI-exact gates at
this head: `check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` exit 0 (1222 == 1222 against base
971e536838ca); pr-base with the ci.yml exact argv (`--base "$PR_BASE"
--labels "$PR_LABELS"`): a stacked cursor/ base exits 1 with the
retarget-to-develop instruction while `--base develop` exits 0 — the
ADR-095 stacked-flow expectation, matching the hosted snapshot.

## Verification evidence (verifier round, head 982dd991edd589af)

The prior launch block — "Hosted PR snapshot incomplete or not the review
head" — is resolved at this head too: the dispatch snapshot of PR #2425 is
complete (`complete_for_scope` true, 80+ check runs captured
2026-11-21T14:05Z) and the hosted PR head sha equals 982dd991edd589af113324
a83c7530592a15cb78, the local review HEAD. The delta vs the verified parent
ba88f29b1cc44c0d is this round's docs commit alone (one inventory-note
append); `reconciliation.py` keeps sha256
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79 — the P4b
code under review is byte-identical across all proven rounds.

Everything below was re-executed fresh at exactly this head, not assumed:
driver deterministic checks inspected green (check-0..8: uv sync, `ruff
check`, `ruff format --check` 3610 files, focused battery 441 passed /
140 skipped, hive-conductor audit pagination 32 passed, suite inventory
ok ×4: hive-conductor backend 4273, maistro-canvas 633, maistro-core 18772,
maistro-rsi 1797) and independently re-run: `ruff check` + `ruff format
--check` clean; focused battery re-executed at 441 passed / 140 skipped.
Fail-before re-proven with the pre-P4b `persisted.cancellation_cause or
cancellation` fallback in `_reconcile_cancelled`: fails exactly
test_unknown_cancelled_refuses_even_with_caller_recovered
(RecoveredDispositionRefused instead of the required RunIntegrityError,
1 failed / 4 passed); restored byte-identical (sha256 verified above,
`git status` empty) and green again (5/5).

Live-database leg on a throwaway pgvector:pg18 container (port 5433,
`DATABASE_URL` for alembic, `alembic upgrade head` to 068,
MAISTRO_TEST_PG_DSN as a raw asyncpg `postgresql://` DSN): the full P4b
battery 581 passed with zero skips — all 140 service-gated legs green,
matching the prior round's count exactly; pg disposition + disposition
suites re-run individually 39 passed; container removed after. Canvas
race-coverage remediation tests re-run green
(test_race_or_require_terminal_resolves_or_refuses,
test_reclaim_recovered_attempt_falls_back_when_reclaim_raises_or_returns_none).
CI-exact gates at this head: `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` exit 0 (1222 == 1222
against base 971e536838ca); pr-base with the ci.yml exact argv
(`--base "$PR_BASE" --labels "$PR_LABELS"`): a stacked cursor/ base exits 1
with the retarget-to-develop instruction while `--base develop` exits 0 —
the ADR-095 stacked-flow expectation, matching the hosted snapshot where
coverage (no services), exact-debt-ledger, and every other completed job
are success and pr-base is the only completed failure.


## Verifier round at review head 32cc253cdbbd (2026-11-21T15:0xZ snapshot)

The prior round's blocker is closed by the hosted snapshot itself: PR #2425's
head on GitHub is now 32cc253cdbbddc267 — exactly this local review HEAD — and
the snapshot is `complete_for_scope` true with 81 check runs captured at that
sha. 80 completed success; pr-base is the only completed failure, and the
cause is proven structural, not a code defect: `.github/branch-protection.json`
topic prefixes are feat/bug/fix/idea/doc/docs/chore, so a PR stacked on a
`cursor/` base fails by design until retarget. Re-executed with ci.yml's exact
argv: `--base cursor/m1-b-p4a-recovered-disposition-8551` exits 1 with the
retarget-to-develop instruction; `--base develop` exits 0.

Everything below re-executed fresh at exactly this head; no source file was
edited (verifier round). `reconciliation.py` sha256 re-verified
5200bb08b7d73a63a69450696b3bdb71c87bf595a48705b7a24cdcc666fa8e79 — byte-
identical to every proven round. Driver deterministic checks inspected green
(check-0..8: sync, ruff check, format --check 3610 files, battery 441 passed /
140 skipped, hive-conductor pagination 32 passed, suite inventory ok ×4) and
independently re-run: core disposition suites (provenance, recovered
disposition, leaseless orphan, recovery events, evidence pack, spine
conformance, canonical store, recovery disposition) 367 passed / 140 skipped
without services; canvas race/reclaim selection 8 passed; CI-exact
check-vulture-baseline.py exit 0 (1222 == 1222, candidate 32cc253cdbbd vs base
971e536838ca); live-database leg on a throwaway pgvector:pg18 container
(alembic upgrade head -> 068, MAISTRO_TEST_PG_DSN set): 554 passed / 0 skipped
across canvas + core disposition suites — every service-gated leg green;
container removed after. Fail-before evidence stands from the two prior
mutation rounds at this same reconciliation.py sha, plus CI's Mutation gate
(changed critical lines) success at the review head.
