---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-48-hitl-answer-recovery

Adds a canonical durable HITL regression for a crash after the accepted answer continuation is persisted and the canonical Run mirror has not yet transitioned. The test verifies targeted restart repair, successful resume, and preservation of physical Attempt history while a new Attempt completes.

## Independent verification at f35b1bd9edbfb2740a5f6f79e5ba4251f17181c3 (2026-09-23)

Executed in the lane worktree; no code edits. All issue #48 acceptance
criteria were re-derived and exercised against this tree:

- `uv run pytest packages/maistro-core/tests/graph/durable_runs/ -q` — 473
  passed, 21 skipped (incl. the settlement and continuation-conformance
  suites this note's delta names).
- `uv run pytest packages/hive-conductor/backend/tests -q` — 2656 passed,
  1 skipped. The four isolated lane suites also pass alone.
- `uv run ruff check .` and `uv run ruff format --check .` — clean;
  `uv run mypy packages/*/src` (six packages) — clean.
- Quality-gate scripts re-run locally: radon baseline, vulture ledger
  (1415 -> 1414), reachability + dispositions, convergence matrix,
  enumerations, doc links, contract markers, security inventory, image
  inventory, agent-store writes, durable-table inventory, wiring reads
  (base 750edd84), version consistency — all green.
- Diff-coverage gate re-run from locally produced coverage data (full
  maistro-core tests + full hive-conductor backend tests, branch arcs):
  `check-diff-coverage --base 750edd84` — all 4 changed production files at
  or above 90% lines / 80% branches.
- CI at this head: Quality gate and Coverage gate both SUCCESS (the
  7adbf77 failures are repaired). Two failures remain — `Supply chain
  (pip-audit)` and `security` — with one shared network fault, not a
  finding: pip-audit could not reach the PyPI advisory API
  (`ReadTimeoutError: pypi.org:443 ... read timeout=15` in both job
  logs), left `pip-audit.json` empty, and the gate crashed parsing it
  (JSONDecodeError char 0). The same workflow passed on the base SHA
  750edd84 thirteen minutes earlier, and this branch touches no
  dependency manifests. Recorded as environmental; a re-run is the
  remedy, not a code change. (The `security` job failure was omitted
  from the f35b1bd record above; ground truth was fetched read-only
  from the check-runs API during the repair pass.)

## Repair-pass verification at 8936ac61b8a4add0277bd1896061c0a66592b7f5 (2026-09-23)

The prior verify job's evidence was rejected only because this docs commit
landed mid-verification (`failure_kind: worktree_changed`); the tree at this
head adds no production or test code over f35b1bd. Everything re-executed:

- `test_hitl_settlement.py` + `test_continuation_conformance.py`: 72
  passed, 14 skipped. Full `durable_runs/` suite: 473 passed, 21 skipped.
- `test_hitl_door.py` + `test_hitl_timeout_cancel.py` +
  `test_dag_agents.py`: 41 passed. Full hive backend suite: 2656
  passed, 1 skipped.
- `ruff check .`, `ruff format --check .`, `mypy` (six `packages/*/src`
  trees), `check-suite-inventory` for both touched suites: all green.
- Quality-gate scripts with the CI spellings: radon, reachability
  (1115 modules / 189 unreachable), wiring-reads, doc-links,
  enumerations, version consistency, contract markers — all exit 0.
- Vulture: `scripts/check-vulture-baseline.py` with **no args exits 1**
  locally and that failure is a measurement-scope trap, not branch debt —
  the default scan is `packages tests`, while the Quality gate's own
  workflow step invokes `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`. With the CI
  invocation this head exits 0 (1415 reviewed identities -> 1414
  findings, matching CI's log at f35b1bd). Verifiers after this lane
  must use the workflow's argument spelling before reporting a vulture
  regression.
- CI ground truth (read-only API) at pushed head f35b1bd: Quality gate
  SUCCESS, Coverage gate SUCCESS, all test/e2e jobs SUCCESS incl.
  `hive-conductor-e2e-ui`; the only two failures are the pip-audit
  network fault documented above. This head differs from f35b1bd by this
  note only.

## Independent verification at cb7ec38f8ada265aea0b89324df94c1100f95b0d (2026-09-24)

Post-merge verify pass: this head is 8936ac61 plus a merge of develop
1dea30df; `git diff 8936ac61..cb7ec38f` over every lane surface (durable_runs
src+tests, hitl route, dag_agents service, hitl door/timeout/dag tests) is
empty, so the previously verified HITL code is byte-identical here. All
checks re-executed in this tree anyway:

- `test_hitl_settlement.py` + `test_continuation_conformance.py`: 72
  passed, 14 skipped (matches the driver's check-3 exactly).
- `test_hitl_door.py` + `test_hitl_timeout_cancel.py` +
  `test_dag_agents.py`: 41 passed (matches check-4).
- Full `durable_runs/` suite: 473 passed, 21 skipped. Full hive backend
  suite: 2663 passed, 1 skipped (= the 2664 suite-inventory count; the
  +8 over the pre-merge 2656 are develop's own tests, folded by the
  inventory check, which passes for both suites).
- `ruff check .` and `ruff format --check .`: clean (2533 files).
  `mypy` over the six `packages/*/src` trees: clean, 713 files.
- Quality-gate scripts at this head: reachability (1117 modules / 188
  unreachable), doc-links, contract-markers, wiring-reads,
  execution-lifecycles (19 classified), `check_enumerations.py`,
  `bump_version.py --check` — all exit 0.
- PR #1327 body and every branch commit message: no closure keywords
  (body says "Refs #48" only).
- Live CI (read-only API) at this head: Quality gate SUCCESS, security,
  SAST, and Supply chain (pip-audit) all SUCCESS (the f35b1bd pip-audit
  network fault did not recur); lint-and-type-check, postgres pg17/pg18,
  MinIO, durable-events, strike-ladder, hive-conductor-e2e/-e2e-ui,
  wheel-imports SUCCESS. Coverage gate, CI `test`, integration-scope,
  docker-build, and gates-ran were still IN_PROGRESS at review time and
  are recorded as UNVERIFIED-pending, not inferred green.

## Repair-pass verification at 57ddca502ba75c20de093f78eef522c01d98d382 (2026-09-24)

Head is 57ddca502 (cb7ec38f plus this note's own post-merge record); the
HITL production surfaces are byte-identical to cb7ec38f. This pass closed
the two gaps every earlier record left: the Postgres conformance legs ran
for real, and the Coverage gate was reproduced from locally produced
data at the CI argument spelling. Evidence:

- **Postgres legs executed, not skipped.** Throwaway pg18 container,
  `alembic upgrade head`, then `MAISTRO_TEST_PG_DSN` set:
  `test_continuation_conformance.py` + `test_hitl_settlement.py` = 86
  passed, 0 skipped (the 14 pg-parametrized conformance legs — keyset
  paging, deadline query, pre-index backfill — now actually ran).
  Full `durable_runs/` suite with pg: **494 passed, 0 skipped**.
- Full hive backend suite: 2663 passed, 1 skipped. Targeted
  door/timeout/dag triplet: 41 passed.
- `ruff check .` / `ruff format --check .`: clean (2533 files). `mypy`
  over the exact ci.yml nine-package battery (core, server, turing,
  canvas, bootstrap, registry, evolve, rsi, design): clean, 775 files.
  (Running only `packages/maistro-core/src` reports 5 import-not-found
  errors for `maistro_bootstrap.*` — a checking-environment artifact,
  not branch debt; the full battery resolves them.)
- Quality gate scripts, all exit 0: radon baseline, xenon (0 block
  violations vs baseline 77), vulture ledger, reachability +
  dispositions, convergence matrix, credential authority, wiring reads,
  agent-store writes, contract markers, security inventory, image
  inventory, backlog consistency, enumerations, doc links, release
  consistency, `bump_version.py --check`, execution-lifecycles (19
  classified).
- **AC-state ratchet + mandate at the develop base 1dea30df, with pg:**
  `check-ac-state.py --run-tests --ratchet --mandate 1dea30df` — ratchet
  OK (10 counters on ceilings, 1 on floor, grant #729 honored),
  acceptance mandate OK (0 unproven touched criteria), chain mandate OK.
- **Coverage gate (diff half) reproduced locally**: `coverage run
  --branch` over full `durable_runs/` + full hive backend, then
  `check-diff-coverage coverage.xml --base 1dea30df` — "ok: every
  measured file this change touches is at or above 90% lines / 80%
  branch arcs" (4 measured production files; 5 test files exempt).
  The publish-set 87% aggregate is unaffected: this branch only adds
  covered lines to maestro-core. **Verifier trap:** scoping coverage to
  only the two targeted core test files makes `attempt_executor.py`
  branch arcs 75% (the `reconcile_persistence is not None` False arc at
  line 198 is covered by resume tests elsewhere in the package, not by
  the settlement suite) and fails the gate spuriously — measure at the
  suite scope CI uses before reporting a coverage regression.
- Acceptance criteria re-derived at this head: waiting is durable and
  tied to Run + NodeRun + `pauses` metadata (fold pauses human results
  to `PAUSED`); answer/timeout/cancel are store-owned, serialized,
  deadline-deterministic and restart-safe (survive-restart tests pass on
  memory, SQLite, and now Postgres); resume keeps the yielded Attempt
  and creates ordinal 2 (attempts `[1, 2]` both COMPLETED) while timeout
  preserves the single Attempt; `/v1/hitl/pending` reads canonical
  `PAUSED` Runs workspace-scoped with an advancing keyset cursor;
  `hitl_settlements` stays evidence-only and the routes translate store
  refusals without re-deciding lifecycle; standalone human work is
  refused (`test_standalone_registered_human_work_is_refused`,
  `test_hitl_store_requires_the_canonical_graph_spine`).
