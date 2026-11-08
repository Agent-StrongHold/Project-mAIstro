# Issue #860 repair — job 1a50e3cf

## Frozen scope

Only issue #860 on `auto-860`, starting at
`16f0ad2842c980a4e4571cf1e39cdc7a243c96f3`, with supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
No remote mutations or develop-sync conflict are present.

Review scope: supplied dispatch context and prior failure/result, repository
instructions, relevant execution/soak ADRs, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, production rate/admission dependencies,
and the exact vulture CI command. Amend `quality/vulture-baseline.json` only
if the executed scanner provides evidence requiring that authorized repair.
This report is the only planned new file; tests/inventory notes will change
only if a demonstrated repair requires tests.

Assumption: writer lane (explicit assigned repair), not read-only verifier.
The job directory contains no `check-*.log` at initial snapshot; inspect the
explicit prior failed log instead. Prior acceptance claims are not proof.

## First validation checkpoint

The exact vulture command passes: 1323 reviewed identities / 1323 findings,
zero unclassified and never-allowlist findings. No ledger edit is justified.
The supplied historical `check-3.log` is a 24-versus-21 schema-test statement
count failure. Fresh targeted execution of learning persistence, soak gates and
HTTP concurrency-backpressure tests passes: **103 passed, 6 skipped** (2.48s).
Raw local logs: `/tmp/860-1a50-vulture.log`, `/tmp/860-1a50-tests.log`.
No source or test repair is justified by these results. Existing branch content
is preserved in full.

Second checkpoint: `uv run ruff check .` and `uv run ruff format --check .`
pass (3270 files). `uv run python scripts/check-ratchet-provenance.py` passes
(53 consumers; existing invalid-escape SyntaxWarnings), and
`uv run python scripts/check-shipped-surface-truth.py` passes. All validation
commands used 1200-second timeouts. The gates selected trusted base
`4aa68edc0b6b` under repository policy, without a base override.

Fresh acceptance review confirms the runner always fails exact-RC artifact
identity (`scripts/soak/run_soak.py:730`), cancels the unexecuted occurrence
probe (`:1044`), and measures driver rather than application event-loop lag
(`:1409`). The executed production-middleware regression at
`tests/test_soak_promotion_gates.py:439` confirms a second replica gives the
same identity a second independent allowance (anonymous and authenticated).
These are not evidence of a completed production soak.

## Architecture and repair disposition

Read `AGENTS.md`, `docs/README.md`, the captured issue body and linked PR
bodies, load profile, adjacent tests and accepted ADRs 081226-a66b,
081626-f383, 082526-b36a and 082426-82c7. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model. The later lease ADR
adds renewal/reclamation beyond the initial fencing ADR; occurrence admission
is not physical execution. No competing authority or acceptance waiver added.

The historical failure is already addressed in the starting tree:
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-179`
independently lists the three additional Gauntlet columns. Production executes
these within the advisory-lock transaction at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215-226`.
The fresh passing test validates that ordering; it does not replace a live
concurrent database boot (six database-dependent tests skipped).

## Acceptance matrix

No production deployment or long soak ran during this attempt. The following
are **UNVERIFIED at promotion grade**, not claimed passes from unit tests:

| Criterion | Fresh evidence and outstanding work |
| --- | --- |
| Representative RC load profile | `scripts/soak/run_soak.py:1373-1395` uses one credential and health/task/receipt/metrics traffic. Concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and background reconciliation are not represented. RC applicability remains UNVERIFIED. |
| At least two deployed replicas | Tests exercise two instances of production middleware via ASGI, not two deployed immutable RC replicas. UNVERIFIED. |
| Sustained saturation, queue growth, reclaim, retries and leaks | Sampler/accounting tests pass, but no sustained deployed observation window was executed. UNVERIFIED. |
| Physical-work uniqueness, admission and Goal reconciliation | Admission probe cancels the queued Run without execution (`run_soak.py:1044-1069`). Physical-effect uniqueness, stale Attempt fencing and sustained Goal reconciliation remain UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes: each instance gives `[200,200,429]`. Middleware is installed in `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32-37` documents N-times allowance. Shared-budget interpretation is falsified locally; overall criterion UNVERIFIED pending contract resolution and deployed testing. |
| Complete telemetry with explicit thresholds | Driver-loop lag is not application-loop lag (`run_soak.py:1409-1421`). No fresh RC pool/query/lock/worker/RSS/fd/queue/error series. UNVERIFIED. |
| Active-work restart, drain, fencing and recovery | Existing restart code (`run_soak.py:1428-1487`) observes HTTP deltas and rejoin, not a physical-effect/stale-worker recovery oracle. No active-work restart executed. UNVERIFIED. |
| Long unchanged exact-RC soak | BLOCKED / UNVERIFIED: no designated immutable promotion artifact/configuration supplied. Host preflight always fails `exact_rc_artifact`; passing CLI regression tests verify fail-closed behavior, not a four-hour RC soak. |
| Findings disposition before promotion | Local gaps recorded here; no new load findings claimed. External filing/reclassification UNVERIFIED; GitHub mutations prohibited and not attempted. |
| Machine/human evidence bound to artifact/config hashes | This report binds validation to the starting commit only. No new hash-bound RC soak evidence collected; historical artifacts not relabeled. UNVERIFIED. |

## Handoff

**BLOCKED**: the supplied CI failure is not reproducible; the exact vulture
ledger needs no amendment. No production/test/ledger/grant changes are warranted
by the fresh check results. Only this report changes; no test additions or count
changes, so no inventory-delta note is needed.

Next: designate the immutable RC and supported configuration, resolve the
replica-local budget contract, implement representative production-path workloads
and physical-effect/recovery oracles with application telemetry, then execute
the unchanged long RC soak. Repeating gate-only repairs cannot prove these
acceptance criteria. Do not weaken the exact-artifact gate.

Progress: checked 1, done 0 acceptance-complete, skipped 0 issues, errors 0
validation failures. Local commit is a blocked handoff, not integration approval.
