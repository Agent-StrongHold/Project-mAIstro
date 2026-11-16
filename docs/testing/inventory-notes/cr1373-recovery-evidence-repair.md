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

## Round: post-merge repair validation (`fb9a8d5cf`, develop `f8a2df966` folded in)

No source or test change this round. The merge-queue evaluation at `4f0b6ecb`
failed `integration-scope` plus ten Quality legs in one run whose BFCL log
shows `##[error]fetch failed` — a runner network outage, and the aggregator's
own block reads "Hosted PR snapshot incomplete or not the review head"
(evidence waited on a SHA that was not the review head). Every named leg was
reproduced locally with CI's exact commands at the new merged HEAD
(`fb9a8d5cf`, develop `f8a2df966` — nltk bump, canvas.runner wiring, hive
project onboarding routes, ADR-048 session search, events/recipes EventBus
subscription, and the M1 retention closeout — all content develop already
greened through its own queue):

- Driver checks at HEAD: ruff check, ruff format (3,562 files), targeted
  durable-runs/a2a/delegate/stores-gaps pytest (250 passed, 31 skipped),
  conductor DAG/registered-DAG recovery (28 passed), both suite inventories
  (Hive 4,199; Core 18,500) — all exit 0.
- Broader recovery signal at HEAD: full `durable_runs` 795 passed / 76
  skipped / 4 xfailed; `a2a` + delegate-remote 316 passed; mypy `--strict`
  packages/maistro-core/src clean (839 files, CI's exact command after
  `uv sync --locked --all-extras`).
- Named CI-failed legs, each with the workflow's exact step command:
  doc links (3,197 files, 0 broken), IFEval provenance (5 artifacts OK),
  BFCL provenance (13 artifacts + shim OK), agent store writes OK, model
  egress (16 callers, no candidate-approved expansion) + design model
  egress OK, all 13 interrogate docstring-floor commands OK (after
  `uv pip install interrogate`, per the workflow's own setup), Hypothesis
  `formal/` 666 passed / 4 skipped (after `uv pip install -e
  packages/maistro-evolve`, per the workflow's own setup).
- durable-events reproduced on a fresh postgres:17 scratch container with
  `MAISTRO_REQUIRE_PG_LEGS=1`: events suite 513 passed / 5 skipped (PG legs
  required, none skipped-as-untested) and event-schema agreement 5 passed.
- strike-ladder reproduced on a fresh postgres:17 scratch container with
  `MAISTRO_REQUIRE_PG_LEGS=1`: 40 passed (the first run errored only because
  the container was still initializing; green after `pg_isready`).
- integration-scope reproduced with the workflow's exact steps at HEAD:
  `ci_base_revision.py` resolves `f8a2df966` from the merge-group event;
  `ci_merge_group_scope.py --json` over the 28 changed paths yields
  docker_build/durable_events/hive_e2e/postgres/strike_ladder/wheel_imports
  = true, object_storage = false; `check-integration-scope.py --required-json`
  resolves the same eight required checks as prior rounds;
  `node --test tests/ci/integration-scope.test.cjs` 12/12. The classifier
  logic is sound; the CI failure was the hosted snapshot/evidence leg.
- acceptance-state `--run-tests --ratchet --mandate f8a2df966` over a fresh
  pg18 scratch database (migrated chain to head): first run failed exactly as
  documented in earlier rounds — an unbanked design_coverage improvement
  (44.4608 measured vs the branch note's 44.26 floor, raised by develop's
  own doc/spec content in the merge). Banked 44.4608 into this branch's own
  `quality/ac-state-notes/auto-62.json` per the gate's instruction
  (`--bank` writes only that branch-scoped file) and re-ran the CI-shaped
  command: exit 0, 10 debt counters exactly on ceilings, 1 progress counter
  exactly on its floor, 0 unproven criteria, 0 chain violations. No shared
  ledger or grant was edited.
- CI-exact ratchets re-run at HEAD for the aggregate gate: vulture
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  1238/1238 banked), radon (126/126), reachability (1,485 modules, 88
  unreachable attributed) + dispositions, convergence-matrix (52 subsystems),
  durable-table-inventory (125 tables, develop-raised baseline),
  execution-lifecycles (19 classified, 3 CANONICAL), backlog consistency —
  all exit 0.

Not re-run locally this round: the postgres matrix, wheel-imports,
docker-build and hive-conductor e2e image builds (none in the failing set;
the image builds previously died on local buildkit DNS, documented above),
and diff coverage (needs CI's full coverage producer; the branch's source
diff is unchanged for the files validated in the prior round).

No test was added or removed this round, so the recorded inventory counts
are unchanged; this note documents validation only.

## Round: independent verification (`0264e6e2`, develop `f8a2df966` merged at `fb9a8d5cf`)

Verifier/writer round; no source or test change. The prior round's merge
resolution and validation were re-checked from scratch rather than assumed:

- Branch state: HEAD `0264e6e2` is clean; develop tip `f8a2df966` is an
  ancestor (`git merge-base --is-ancestor` OK), so the merge-queue conflict
  is resolved; `fb9a8d5cf..HEAD` is docs-only (this note + the
  `quality/ac-state-notes/auto-62.json` design_coverage re-bank).
- Driver checks re-read: ruff check, ruff format (3,562 files), targeted
  recovery pytest (250 passed/31 skipped), conductor DAG/registered-DAG
  recovery (28 passed), both suite inventories (Hive 4,199; Core 18,500) —
  all exit 0.
- Re-run independently at HEAD: full `durable_runs` 795 passed / 76 skipped /
  4 xfailed; conductor recovery 28 passed; waker-mapping + crash
  reconciliation set (pause-reason wakers, cross-store reconciliation, A2A
  receipt wakers) 101 passed / 31 PG-leg skips; vulture CI-exact 1,238/1,238
  banked; doc links 3,197 files / 0 broken (covers the note committed after
  the previous gate pass); IFEval provenance (5 artifacts), BFCL provenance
  (13 artifacts + shim), agent store writes, model egress (16 callers) +
  design model egress, all 13 interrogate docstring floors (venv-only
  `uv pip install interrogate` per the workflow's own setup), Hypothesis
  `formal/` 666 passed / 4 skipped (`uv pip install -e packages/maistro-evolve`
  per the workflow's own setup), integration-scope classifier
  `node --test tests/ci/integration-scope.test.cjs` 12/12 — all exit 0.
- durable-events re-proven on a fresh postgres:17 database inside the
  retained scratch container, CI-exact env (`MAISTRO_REQUIRE_PG_LEGS=1`):
  events suite 513 passed / 5 skipped; event-schema agreement 5 passed.
- strike-ladder re-proven on a fresh `strike_test` database, CI-exact env:
  40 passed with the PostgreSQL leg required.
- acceptance-state re-proven CI-shaped (`--run-tests --ratchet --mandate
  f8a2df966`) over the migrated retained pg18 scratch database: exit 0; the
  committed re-bank (44.4608) is exactly the measured value; 10 debt
  counters on ceilings, 1 progress counter on its floor, 0 unproven
  criteria, 0 chain violations.

Still not locally executable (unchanged from prior rounds, documented above):
docker-build and hive-conductor e2e image builds (local buildkit DNS), the
full postgres matrix and wheel-imports (not in the failing set; source diff
unchanged since they last passed), OS-kill durability and full admission
matrices for parent #62 rows (CI-only producers), and diff coverage (needs
CI's coverage producer).

No test was added or removed this round, so the recorded inventory counts
are unchanged; this note documents validation only.

## Round: container-scan repair (`b868e47f9` head; Dockerfile docker-CLI CVE bump)

The remaining failing leg at head `b868e47f9` was the merge-queue
`Container scan + SBOM + cosign` job (run 43804171165, job 133090992402).
The failing step, read from the authenticated job log, is **Trivy scan
maistro-engine (HIGH/CRITICAL only)** — the npm-audit lines in the excerpt
previously quoted from the log tail are the tail of an earlier `npm ci`
build step, and `npm ci` does not fail on audit findings (reproduced
locally with npm 9.2.0/node 22: a critical-vulnerability tree installs
with exit 0). The real findings, identical to the local reproduction:

- `usr/local/bin/docker` (gobinary): go-jose/v4 4.1.5 — CVE-2026-116587
  (HIGH, fixed 4.1.6) and golang.org/x/net 0.60.0 — CVE-2026-78661
  (HIGH, fixed 0.62.0). Both are vendored by docker/cli v29.9.1
  (`vendor.mod`, commit `dfc520d`), the tag the root `Dockerfile` and
  `Dockerfile.research` build the shipped CLI from.

Fix (both Dockerfiles, same stage, byte-identical): bump
`DOCKER_CLI_VERSION` to 29.9.3 (commit `5457199`, resolved through the
annotated tag API; the in-stage `git rev-parse --short=7` check still
pins it) and patch `golang.org/x/net` to v0.62.0 onto that tag with
`go get` + `go mod vendor` — the same policy the `agebuild` stage uses
for x/crypto and the root Dockerfile documents for toolchain CVEs.
v29.9.2 vendors both advisories unfixed; v29.9.3 vendors go-jose 4.1.7
upstream but still pins x/net 0.60.0, so the tag bump alone cannot close
the second advisory (checked upstream vendor.mod for v29.9.2, v29.9.3
and latest tag list before choosing). No repo surface asserts the CLI
version (`tests/test_prepull_copy_sources.py` checks only the stage-alias
property, unchanged).

Proof on this machine (docker 29.1.3 server, trivy 0.73.0 with a fresh
mirror.gcr.io/aquasec/trivy-db:2, image-mode scan like CI):

- Old stage built verbatim from `git show HEAD:Dockerfile`:
  `out/docker` scans **2 HIGH** — exactly CVE-2026-116587 (go-jose
  4.1.5→4.1.6) and CVE-2026-78661 (x/net 0.60.0→0.62.0), the same table
  the CI log shows.
- New stage: builds clean (`go get`, `go mod vendor`, vendored
  `-tags grpcnotrace` build all succeed); binary reports
  `Docker version v29.9.3, build 5457199`; image scan reports
  **0 HIGH/CRITICAL** for `out/docker` (and the go toolchain binaries
  in that build-only stage).
- The research image's CLI stage is byte-identical (diffed), so the
  same proof transfers to the maistro-engine-research scan that CI
  never reached.

Driver battery re-run at `b868e47f9` (the prior job's own logs
`check-0..6` also passed all seven checks with returncode 0 — that job
died on a provider 404 (nous/poolside/laguna-s-2.1:free), i.e. driver
infrastructure, not a repo check):

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- CI-exact vulture: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` —
  exit 0, 1238/1238 banked, no ledger amendment needed.
- `durable_runs` full suite: 795 passed / 76 skipped / 4 xfailed;
  M1-E2 convergence + cross-store reconciliation + stores-gaps:
  120 passed / 31 skipped (PG legs skipped without a database);
  a2a delegate/guest-peers/remote: 130 passed; conductor DAG +
  registered-DAG recovery: 28 passed.
- Both suite inventories ok (Hive 4,199; Core 18,500).
- CI-shaped convergence gates: `check-m1-convergence-freeze.py --base
  origin/develop`, `check-convergence-matrix.py` (52 subsystems, 1485
  modules, 88 unreachable attributed) and `check-execution-lifecycles.py`
  (19 classified, 3 CANONICAL) — all exit 0.
- Production-level retirement check for ADR-083026-6e2a: no
  `checkpoints` module and no `canonical_checkpoints` reference exists
  under `packages/*/src`.

No test was added or removed this round, so the recorded inventory counts
are unchanged; this note documents the container-gate repair and validation.
