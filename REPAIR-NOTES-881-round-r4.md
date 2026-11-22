# Round-4 repair notes for issue #881 (`auto-881`, head `afdbeb090`)

## What the driver reported

The merge-queue evaluation reported two failing gates at head
`afdbeb0905f44c4e1822efa94291601e9ed5727b`:

- `integration-scope` — "docker-build is required by integration scope but
  concluded cancelled".
- `postgres (pg${{ matrix.postgres }})` — "unavailable (RuntimeError); run the
  named gate locally to reproduce".

and instructed a vulture per-identity ledger repair with
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'`.

## What the evidence actually shows

Both reported failures are **superseded check-runs from a cancelled first
wave**, not a defect in this branch. The check-run timeline for the candidate
SHA (from `checks.listForRef` in the dispatch context; 142 check-runs in all):

| started | completed | name | conclusion | check-run id |
|---|---|---|---|---|
| 13:19:34Z | 13:19:34Z | `block` | cancelled (wave 1) | 119245676669 |
| 13:19:35Z | 13:19:35Z | `docker-build` | cancelled | 119245688118 |
| 13:19:35Z | 13:19:35Z | `postgres (pg${{ matrix.postgres }})` | cancelled | 119245687828 |
| 13:19:38Z | 13:19:49Z | `integration-scope` | **failure** | 119245686985 |
| 13:19:38Z | 13:19:46Z | `SAST (bandit + semgrep + gitleaks)` | failure (wave 1) | 119245683420 |
| 13:19:39Z | 13:19:45Z | `Quality gate (Pillars 1–4, 7, 8)` | failure (wave 1) | 119245696040 |
| 13:20:15Z | 13:27:40Z | `docker-build` | success | 119245924324 |
| 13:20:12Z | 13:24:59Z | `postgres (pg17)` | success | 119245924476 |
| 13:20:15Z | 13:25:09Z | `postgres (pg18)` | success | 119245924453 |
| 13:22:45Z | 13:22:52Z | `SAST (bandit + semgrep + gitleaks)` | success | 119247280705 |
| 13:24:40Z | 13:24:48Z | `Quality gate (Pillars 1–4, 7, 8)` | success | 119248218033 |
| 13:35:25Z | 14:00:15Z | `Coverage gate (publish-set floor + diff coverage)` | success | 119253679486 |

1. The first wave (ids `11924567…`–`11924569…`) was created at 13:19:34Z and
   cancelled within one second of each other at 13:19:34–35Z — the
   merge-queue re-queue cancelling the superseded attempt. 67 of the 142
   check-runs are that wave.
2. `integration-scope` (119245686985) started at 13:19:38Z and **failed 11
   seconds later**, with the message the driver quoted. The mechanism is in
   `.github/workflows/integration-scope.yml`: the polling step keeps the
   highest check-run **id** per name ("a newer queued/cancelled/failed attempt
   must supersede success") and fails closed on the first non-success
   conclusion —
   `core.setFailed(\`${name} is required by integration scope but concluded
   ${run.conclusion || '<none>'}\`)`. At its first poll the only
   `docker-build` check-run for the SHA was the cancelled one; the replacement
   did not start until 13:20:15Z, **26 seconds after the aggregator had
   already given up**, and succeeded at 13:27:40Z — eight minutes too late
   for a loop that returns on the first non-success conclusion instead of
   re-polling. This is a race in the shared aggregator, not in the candidate:
   the required leg itself is green.
3. `postgres (pg${{ matrix.postgres }})` is the *unexpanded* job name. Per
   `ci.yml`'s own comment above that job ("GitHub evaluates job-level `if`
   before expanding the matrix; skipping here reports only an unexpanded
   name, not postgres (pg17) / postgres (pg18)"), a job that is cancelled
   before matrix expansion is reported under exactly that name. The expanded
   `postgres (pg17)` and `postgres (pg18)` jobs both concluded **success** for
   this SHA.
4. The same wave-1 pattern produced the two other first-wave failures the
   driver did not list: `SAST` (119245683420) and `Quality gate`
   (119245696040) both failed within seconds of starting, and both were
   re-run and concluded **success** (119247280705 at 13:22:52Z, 119248218033
   at 13:24:48Z). `Gate C — canonical clean install` (119245688221) and
   `block` (119245688423) also succeeded. Only `integration-scope` was not
   re-queued, because it is a merge-group-only aggregator.

The required set for this candidate is computed deterministically and is
**`docker-build` alone**:

```
$ git diff --no-renames --name-only 9cc5d1aca...HEAD | xargs \
      python3 scripts/ci_merge_group_scope.py --json
{"docker_build": true, "durable_events": false, "hive_e2e": false,
 "object_storage": false, "postgres": false, "strike_ladder": false,
 "wheel_imports": false}
```

(`docs/`, `formal/` and `.github/` are all docker-build inputs, so the leg is
required whatever the branch touches; the other six legs are out of scope,
and the scope-gated ones were correctly skipped by the merge-group run — the
`postgres` matrix is deliberately not scope-gated and ran anyway, see
below.) `docker-build` concluded **success** for the candidate SHA (job
119245924324), so the evidence integration-scope exists to aggregate is
green.

Hosted evidence at the same SHA, for the record: `formal-conformance`
**success** (119245685614 — the new model ran against a real PostgreSQL in
CI), `exact-debt-ledger` **success** (119245686036), `Quality / Vulture`
**success** (119245775131), `Quality gate (Pillars 1–4, 7, 8)` **success**
(119248218033), `SAST (bandit + semgrep + gitleaks)` **success**
(119247280705), `Coverage gate (publish-set floor + diff coverage)`
**success** (119253679486), `Gate C — canonical clean install` **success**
(119245688221), `block` **success** (119245688423). The scope-gated legs
outside the required set (`durable-events`, `object storage (MinIO)`,
`strike-ladder`, `wheel-imports`, `hive-conductor-e2e`,
`hive-conductor-e2e-ui`) were correctly skipped; the `postgres` matrix is
deliberately *not* scope-gated — ci.yml's own comment says "Required matrix
contexts must exist even for out-of-scope queue changes" — so both of its
legs ran and succeeded.

## The vulture per-identity ledger: no amendment needed

Run with CI's exact arguments:

```
$ uv run python scripts/check-vulture-baseline.py packages/*/src \
      --min-confidence 60 --exclude '*/third_party/*'
...
ratchet: vulture  [vulture (tool version: 2.16), metric v1]
  baseline: base 9cc5d1aca141
  candidate: afdbeb0905f4
  1321 reviewed identities  ->  1321 findings
EXIT=0
```

Candidate findings == baseline rows (1321 == 1321), so there is no unbanked
identity to fix and no reviewed identity to remove. `quality/vulture-baseline.json`
is untouched by this branch, and this round amends it nowhere.

## Independent re-verification of the research note's mutant battery

The note's central claim is that the model has teeth. It was re-run from
scratch at this head: each mutant is a one-line edit to a `PYTHONPATH`-shadowed
copy of `packages/maestro-core/src` (the worktree was never edited), against a
freshly migrated pgvector:pg18, with
`pytest formal/models/test_execution_lifecycle_state.py --hypothesis-seed=0`.

| # | Mutant | Result | First failing test | Wall clock |
|---|---|---|---|---|
| M1 | `_validate_run_transition` → no-op | CAUGHT | machine (`TestExecutionLifecycleMachine::runTest`) | 6.6 s |
| M2 | `check_completion_is_earned` → early return | CAUGHT | `test_completion_of_the_run_is_earned_by_its_latest_node_run` — the **witness**; the machine alone missed it at the PR budget, as the note says | 4.1 s |
| M3 | terminal-run cascade disabled | CAUGHT | machine (`runTest`) | 6.9 s |
| M4 | `refuse_completion_under_terminal_run` → pass | CAUGHT | `test_attempt_completion_is_refused_under_a_terminal_run` | 4.0 s |
| M5 | terminal-NodeRun guard removed from `create_attempt` | CAUGHT | machine (`runTest`) | 30.4 s |
| M6 | terminal-Run guard removed from `create_node_run` | CAUGHT | machine (`runTest`) | 21.9 s |

Six of six caught, and the catching test matches the note's table in every
case — including the honest negative in M2. (Wall clock is the whole pytest
invocation, collection and both deterministic witnesses included; the battery
was run with `-x`, so the first failing test is the one reported.)

## The `postgres` leg, reproduced locally

The job's database steps were reproduced against a real PostgreSQL (a local
pgvector container on port 5570, a fresh database, `alembic upgrade head`
applied, then the persistence suite with the job's exact environment):

```
DB_HOST=127.0.0.1 DB_PORT=5570 DB_USER=maistro DB_PASSWORD=maistro \
DB_NAME=maistro_fresh2 \
MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_fresh2 \
MAISTRO_TEST_DATABASE_URL=postgresql://maistro:maistro@127.0.0.1:5570/maistro_fresh2 \
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 MAISTRO_REQUIRE_PG_LEGS=1 \
  uv run pytest packages/maistro-core/tests/persistence -q
835 passed, 84 skipped, 27 warnings in 62.53s
```

Green, with the CI job's exact environment. The same suite without
`MAISTRO_DRY_RUN=1` fails two tests in
`packages/maistro-core/tests/persistence/test_schedule_winner_crash.py`; the
cause is visible in the database and is **not** this branch's:

- that test deliberately leaves its winner Run in flight, and each execution
  leaves one `queued` root Run for the shared `test-actor-principal`;
- the product's `max_active_root_runs_per_principal` floor is 8, so once
  eight such runs accumulate, admission refuses with "active root Run ceiling
  reached for principal: 8 active, limit 8" and the crash worker exits before
  its checkpoint;
- with `MAISTRO_DRY_RUN=1` (the CI postgres job's setting) the earlier
  writers in the suite are dry-run, the count never reaches the ceiling, and
  the suite is green — which is why the hosted leg passed on pg17 and pg18.

`git diff 9cc5d1aca...HEAD -- packages/` is empty: this branch changes no
package code, so the observation belongs to the maistro-core persistence lane,
not to #881. It is recorded here rather than acted on, because this lane
changes no product code and the issue's scope is a research prototype.

## The nightly workflow change, measured

`.github/workflows/formal-conformance-nightly.yml` adds a PostgreSQL service,
so the two Pg-backed models run in the nightly sweep instead of skipping
(`ac_outcome_plugin` counts a skip as no evidence). That is the first time
they have run there, so their cost was measured at the nightly budget:

- `MAISTRO_FORMAL_PG_EXAMPLES=200`, `--nightly`: this module 34.2 s, I29's
  lease/fence model 23.6 s — under a minute together, against a 60-minute job
  budget and a 1800 s per-test timeout.
- `alembic upgrade head` against the service's DSN: applies cleanly.
- `pytest formal/models/test_execution_lifecycle_state.py formal/models/test_run_lease_fence.py --nightly`
  with the DSN set: 4 passed, **no skips** — the nightly path reaches the
  models.

## Changed in this round

1. `docs/research/881-execution-lifecycle-state-machines.md` — the
   "Validation at this head" section described a head that no longer exists
   (it still said 667 collected = 664 before + this change's +3, "38 files
   already formatted", and quoted the pre-sync suite-inventory result). It
   now carries the numbers re-measured at this head (670 formal nodes at the
   head against 667 at the base, 40 formatted files in `formal/`, seeds 0–3
   clean at 3.8–5.1 s, 60-example run 13.5 s, the nightly budget at 200
   examples), plus a new paragraph recording the independent re-verification
   of the mutant battery.
2. `docs/testing/inventory-notes/881-execution-lifecycle-state-machine.md` —
   the deltas were already correct, so the front matter is unchanged; the
   note now carries the re-verified mechanism for `tests/: +1` (7 → 8
   `pg_isready` services, 9 → 10 collected health-check nodes) and the
   re-measured runtimes.
3. This file.

No product code, no ledger, and no grant changed.

## Validation executed locally (all green)

- `uv run ruff check .` → clean; `uv run ruff format --check .` → clean
  (3410 files already formatted).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1321 == 1321.
- `uv run python scripts/check-suite-inventory.py` → ok, 21/21 suites,
  `formal/: 670`, 33140 unique node IDs.
- `uv run python scripts/check-formal-oracle-independence.py --base
  9cc5d1aca141695d747b23bd06a12cce9d8f850d` → OK.
- `uv run python scripts/check-ratchet-provenance.py` → OK.
- `uv run python scripts/check-doc-links.py` → 0 broken relative links.
- `uv run python scripts/check-citation-status.py` → OK.
- `uv run python scripts/check-workflow-inventory.py` → clean (30 workflows).
- `python3 scripts/ci_merge_group_scope.py --json <changed paths>` → the
  required set above.
- `MAISTRO_TEST_PG_DSN=… pytest formal/models/test_execution_lifecycle_state.py`
  → 3 passed (seeds 0–3, and `--nightly`); without the DSN → 3 skipped, as
  the inventory note records.
- `pytest packages/maistro-core/tests/persistence` with the postgres job's
  environment on a fresh database → 835 passed, 84 skipped.

## Residual

- **`integration-scope` is a hosted aggregator and cannot be re-run here.**
  Its only failing prerequisite was the cancelled first-wave `docker-build`;
  the required leg itself concluded success for this SHA. The aggregator's
  first-poll race (it fails closed on a cancelled attempt even when a newer
  attempt is already queued) is develop-side, in a shared workflow this branch
  does not touch.
- **The nightly workflow change has no hosted run yet** — that workflow fires
  on a schedule or `workflow_dispatch`, so the first hosted exercise of the
  new service is the next nightly. The local evidence above covers the parts
  that could break (migrations, the models running instead of skipping, the
  budget), but the hosted run is still owed.
- **The `postgres` matrix is not scope-gated** and both of its legs ran and
  succeeded for this SHA, so the "unavailable (RuntimeError)" the driver
  reported was the merge queue's read of a *cancelled* job, not a missing
  service.
- `formal/README.md` labels `test_sentinel_validator.py` as I29 while
  `test_run_lease_fence.py` calls itself I29 in its own docstring, which this
  note's "I29" references follow. Pre-existing on develop; out of scope here.
- The two invariants the issue lists but this prototype does not reach —
  lane capacity/reservations and receipts-vs-spine contradiction — remain
  documented WATCH items in the research note, in the tasks seam the
  prototype did not model.
