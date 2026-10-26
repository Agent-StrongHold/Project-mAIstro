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

## Round: governed harness polls + paused-sweep rotation (`00a515e52`, merged with develop `4019249e`)

Verifier evidence against `9054f91e` found two reachable gaps, both fixed in
`00a515e52` and re-validated here after the develop merge (`ec801784a`):

1. The external seam polled harness providers without crossing the governed
   Invocation/Binding boundary. The seam now requires the node-persisted
   dispatch Invocation (COMPLETED, correlated with the Run and its Binding
   reference) and a Binding that still resolves in the canonical authority;
   `wake_due_registered_dag_runs` hands it the Container's canonical effect
   authorities (`capability_effects.invocation_store` / `.bindings`).
2. `reconcile_persistence` scanned canonical PAUSED Runs from the top every
   tick, so a persistent parked Run consumed the whole budget at limit=1 and
   terminal failed-Event retry discovery never ran. The paused half is now a
   cursor-advancing fair page like the RUNNING half.

Negative validation (regression tests copied onto a scratch worktree at the
pre-fix commit `9054f91e`, fresh `uv sync --locked --extra dev`): all five
bite — `test_a_revoked_binding_is_never_polled_by_the_seam`,
`test_a_harness_pause_without_governed_dispatch_evidence_stays_parked`,
`test_a_missing_or_foreign_dispatch_receipt_is_left_parked` and the conductor
`test_a_revoked_binding_is_never_polled_by_the_external_seam` fail (the last
asserts `wake_due_registered_dag_runs(limit=1) == 0`, got `1`), and
`test_a_persistent_paused_run_cannot_starve_terminal_event_discovery` fails on
the memory and sqlite params. All five pass at HEAD.

Re-run at HEAD after the merge: full durable_runs suite 783 passed / 70
skipped / 4 xfailed; conductor registered-DAG + DAG recovery 28 passed; ruff
check + format clean; mypy clean (942 source files); vulture exit 0 (1256/1256
identities banked, 0 unclassified); radon exit 0 (127/127); suite inventory ok
(21 suites); backlog, execution-lifecycles, durable-table-inventory,
convergence-matrix and M1-convergence-freeze (`--base 4019249e`) all exit 0.

## Round: post-merge repair validation (`78be6f61d`, develop `10f872fa7` folded in)

No source or test change this round; the prior job died on a provider timeout,
not a check. Validation was repeated at the merged HEAD (develop base
`10f872fa7`, whose admission-replay-classification changes touch
recovery-adjacent seams):

- Verifier battery at HEAD: ruff check/format, targeted durable-runs + a2a +
  delegate + stores-gaps pytest, conductor recovery suites, both suite
  inventories (Hive 4,181; Core 18,369) — all exit 0.
- Full `packages/maistro-core/tests/graph/durable_runs`: 783 passed / 70
  skipped / 4 xfailed; `packages/maistro-core/tests/a2a`: 295 passed;
  conductor recovery: 28 passed.
- CI-exact quality gates at HEAD: vulture
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  1248/1248 banked, base `10f872fa7`), radon ratchet (126/126), mypy strict
  (953 files), doc links, interrogate docstring floors (nodes/durable_runs/
  core/server), IFEval + BFCL vendored provenance, Hypothesis formal/ suite
  (670 passed, editable maistro-evolve installed per the workflow's own
  setup), agent store writes, model egress, design model egress,
  execution-lifecycles, durable-table-inventory (122 tables),
  convergence-matrix (1,486 modules), reachability + dispositions, backlog,
  M1-convergence-freeze `--base 10f872fa7` — all exit 0.
- acceptance-state `--run-tests --ratchet --mandate 10f872fa7` over a freshly
  migrated pg18 database: initially failed on an unbanked design_coverage
  improvement (44.26 measured vs 39.6633 floor folded from notes at the
  develop base); banked 44.26 into this branch's own
  `quality/ac-state-notes/auto-62.json` per the gate's instruction and re-ran
  the CI-shaped command: exit 0, all counters exactly on bounds, mandate OK.
  No shared ledger or grant was edited.
- integration-scope reproduced with CI's exact steps: classifier scope JSON
  well-formed for the branch's 29 changed paths; required set resolved
  (docker-build, durable-events, hive e2e ×2, postgres ×2, strike-ladder,
  wheel-imports); `node --test tests/ci/integration-scope.test.cjs` 12/12.
- Required specialized legs executed for real on this machine at HEAD:
  durable-events (events suite 489 passed + migration agreement 5 passed,
  fresh postgres:17 database, PG legs required); postgres matrix pg17 and
  pg18 — all 12 workflow steps each (migration chain, legacy-principal
  live migration, alembic up/down/up, persistence, container wiring,
  workspaces/personas/goals with PG legs required, hive workspace authority,
  Canvas and Design supported-path E2E); strike-ladder (40 passed, PG leg
  required); wheel-imports (12 wheels built, clean-venv import check passed).
- Not executable locally: docker-build and hive-conductor-e2e image builds
  died on buildkit DNS resolution of files.pythonhosted.org (three attempts,
  `docker run` DNS healthy between attempts — local mirrored-WSL networking,
  the same transient class CI's pre-pull script retries). The
  branch-relevant build step `uv export --locked --package hive-conductor`
  succeeded inside the failing image build each time, proving lock/pyproject
  consistency; no Dockerfile, compose file or uv.lock path is in the branch
  diff. UNVERIFIED locally: the hive api-tests leg and the docker image
  build itself at HEAD.

`check-ac-state.py --run-tests --ratchet` initially failed on an unbanked
design_coverage improvement (measured 39.6633 vs folded floor 39.641, slack a
regression could spend); banked to this branch's own
`quality/ac-state-notes/auto-62.json` per the gate's instruction and re-ran the
CI-shaped `--run-tests --ratchet`: exit 0, all counters exactly on their
bounds. No shared quality ledger or grant was edited. Diff coverage was not
re-measured locally this round (needs CI's full coverage producer); the branch
diff beyond develop is unchanged for source files validated in the prior
round.

## Round: post-merge repair validation (`1619765fa`, develop `1fc3d230` + `407b181` folded in)

No source or test change this round. The pushed head `33c3cce` failed three
CI legs — `Quality / Execution lifecycles`, the `Quality gate` aggregate
(via lifecycles) and `SAST (bandit + semgrep + gitleaks)` (its semgrep leaf
was *cancelled* after 91 s, so the aggregate failed closed) — and the
merge-queue `integration-scope` aggregator stayed non-success because it
requires exactly those legs. The develop merge now at HEAD resolves the code
side: `check-execution-lifecycles.py` (CI-exact, `RATCHET_BASE_REV=origin/develop`)
was re-run at `1619765fa` and exits 0 (19 classified lifecycles, 3 CANONICAL).
Validation at the new merged HEAD:

- SAST reproduced locally with each workflow's exact arguments: semgrep
  (custom rules + p/security-audit + p/owasp-top-ten + p/secrets, same
  excludes) 364 rules on 2268 files, 0 findings; bandit 0 Medium+ on
  maistro-core/src + hive-conductor/backend + maistro-server/src; gitleaks
  `--log-opts=407b181..1619765fa` 18 commits, no leaks.
- CI-exact ratchet gates at HEAD: vulture (1248/1248 banked), radon
  (126/126), reachability + dispositions, convergence-matrix,
  workflow-inventory, durable-table-inventory (122 tables),
  execution-lifecycles — all exit 0. `mypy --strict packages/maistro-core/src`
  clean (840 files) after `uv sync --locked --all-extras` (CI's env; a
  `--extra dev`-only venv fails on the `maistro_bootstrap` import, an
  environment artifact, not a code error).
- Tests at HEAD: full `packages/maistro-core/tests/graph/durable_runs`
  795 passed / 76 skipped / 4 xfailed (six new #1626 walker-death tests
  included and passing), `tests/a2a` 295 passed, conductor DAG/registered-DAG
  recovery 28 passed; both suite inventories ok (Core 18,387; Hive 4,181).
- integration-scope reproduced with the workflow's exact steps:
  `ci_merge_group_scope.py --json` over the 28 changed paths vs `407b181`
  is well-formed and resolves the required set docker-build, durable-events,
  hive-conductor-e2e(-ui), postgres (pg17/pg18), strike-ladder,
  wheel-imports — the same legs that all concluded success on CI at
  `33c3cce`; the merge adds only develop content already green through
  develop's own merge queue.
- acceptance-state `--run-tests --ratchet --mandate 407b181` over a freshly
  migrated pg18 scratch database (`cr1373-round3-pg18`, port 54329): exit 0,
  10 debt counters exactly on their ceilings, 1 progress counter exactly on
  its floor, 0 unproven criteria, 0 chain violations. No ledger or grant
  was edited; `quality/ac-state.json` output is gitignored.

No test was added or removed this round, so the recorded inventory counts
are unchanged; this note documents validation only.
