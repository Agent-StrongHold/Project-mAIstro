# #1572 repair round 2 — evidence at 20a88c52c + truthfulness corrections

Round lane: `auto-1572` @ `20a88c52c90269ad662b9cf6f9ecb0059c3e4f62`,
develop base `0d49d4e068de` (merge base with develop: `d592654aca61`).

## What CI actually shows at this head (read-only API, 2026-10-09)

The round brief named `integration-scope: failure` from the last merge-queue
evaluation. The live check-runs at this head tell a different story:

- `integration-scope`: **success** — all nine required specialized legs
  (`docker-build`, `durable-events`, `hive-conductor-e2e`, `hive-conductor-e2e-ui`,
  `object storage (MinIO)`, `postgres (pg17)`, `postgres (pg18)`, `strike-ladder`,
  `wheel-imports`) concluded **success** at this SHA.
- `exact-debt-ledger`: success.
- `Quality gate (Pillars 1–4, 7, 8)`, `test`, `Coverage gate`: **failure** — and
  all three share exactly one root cause (next section).

## The single red root cause: the GoalStatus lifecycle grant (external, two-merge rule)

`scripts/check-execution-lifecycles.py` fails first-hand with the CI-exact
command (`quality.yml:1520`):

```
19 classified lifecycles  ->  20 discovered lifecycles
FAIL: ...
  - maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
    the trusted base and has no already-landed authorization
```

- The branch classifies the new vocabulary in `quality/execution-lifecycles.json`
  (+4 lines) but `quality/ratchet-authorizations.json` at the merge base
  (`d592654aca61`) has **0** `GoalStatus` entries, and the branch's diff on that
  file is empty — by design: `load_authorizations` reads grants **from the merge
  base**, so a branch can never authorize its own debt (the two-merge rule).
- CI `test` job: only failure is
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  (`AssertionError: assert 1 == 0` — the gate's exit code; 5056 passed / 134
  skipped otherwise in the Coverage-gate run). Same in local run: 1 failed,
  28 passed, identical single finding.
- **Required external action:** land a grant-only change adding the
  `maistro.goals.model::GoalStatus` authorization to
  `quality/ratchet-authorizations.json` **on develop**, then merge
  `origin/develop` into `auto-1572`. The candidate ledger already classifies the
  vocabulary, so after the sync the gate, the shipped-ledger test, the `test`
  job and the `Coverage gate` all have no remaining known failure.

## ac-state is NOT a branch regression (local fall is environmental)

`check-ac-state.py --run-tests --ratchet` measures `design_coverage 39.641`
locally — below the 43.8998 floor folded from the 35 committed notes. Measured
the **base commit `d592654aca61` in this identical environment** (fresh worktree
`/tmp/base-1572-acstate`): byte-identical counters (39.641%, 166 decisions, 89
at zero, 704 markers). The branch's diff therefore has **zero effect** on the
ac-state counters; the shortfall comes from PG-backed AC tests that cannot pass
without Postgres locally. In CI — where the job owns a Postgres service — the
gate **passed**: the Quality-gate log at this head records
`design coverage: 44.2377% over 166 taken decisions (88 at zero)` ≥ 43.8998,
and the job's only failing step is execution-lifecycles. Banking a fall the
branch did not cause would permanently lower the floor for every later branch,
so no `--bank` was (or should be) performed.

## Truthfulness corrections in this round (evidence-based, not cosmetic)

1. `alembic/versions/043_invocation_quota_door.py` docstring claimed the Goal
   DDL "appends as `061_canonical_goals` after `060`". Reality: develop already
   ships `061_hitl_pause_kind_index`; the branch appends
   `062_canonical_goals` (`down_revision = "061"`). Corrected to state the real
   identity and parent — migration-identity claims are load-bearing here
   (installed-base upgrade fixtures pin 056/057 meanings).
2. `tests/migrations/test_run_store_planner_stability.py` renamed
   `test_057s_indexes_exist_and_the_redundant_one_is_gone` → `test_058s_…`
   while the revision that adds those three indexes and drops
   `ix_graph_continuations_status` is untouched `057_run_store_planner_stability`
   (byte-identical to develop; its `upgrade()` carries exactly those statements).
   Restored the `057s` name/docstring so the test names its true subject.

Both changes are count-neutral for
`scripts/check-suite-inventory.py` (`--suite tests/` and
`--suite packages/maistro-core/tests` both report `ok: 1 suite(s) match the
recorded inventory`), so no inventory delta is required.

## Commands executed this round (all first-hand)

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | pass |
| `uv run ruff format --check .` | 3247 files already formatted |
| `uv run pytest packages/maistro-core/tests/goals -q` | 48 passed, 22 skipped (PG legs skip locally; CI `postgres (pg17/18)` runs this suite green with `MAISTRO_REQUIRE_PG_LEGS=1` at this head) |
| `uv run pytest tests/migrations -q` | 38 passed, 127 skipped |
| `uv run pytest tests/test_check_execution_lifecycles.py -q` | 1 failed (GoalStatus grant, matching CI), 28 passed |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | ok |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | ok |
| `uv run python scripts/check-m1-convergence-freeze.py --base d592654aca…` | EXIT 0, no unapproved new architecture island |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | EXIT 0 (1323 → 1323) |
| `scripts/ci_merge_group_scope.py --json <76 changed paths>` + `scripts/check-integration-scope.py --event-name pull_request --required-json` | EXIT 0; required set = the nine legs listed above |

Not re-executed here (Docker daemon unreachable in this session; covered by CI
at this exact head): PG-backed goals conformance, migration chain apply/reverse,
installed-base upgrade fixtures — the green `postgres (pg17)` / `postgres (pg18)`
check-runs at `20a88c52c` own those steps.

## Residual blocker (cannot be repaired inside this worktree)

The GoalStatus grant must land on develop first (two-merge rule). Until then the
Quality gate, `test` and `Coverage gate` remain red at every head of this
branch, regardless of any in-branch change. Everything else at this head is
observably green.
