# Issue #42 validation — fd2eddfa3 (repair round c71bc168)

Verification record for lane L42 (M1-B2 — Finish Attempt → ExecutionRuntime
physical execution integration) at head `fd2eddfa3ad188682936761a3f87360ec7389e5f`
(branch `auto-42`, develop base `1e640df17c8a7dda647afa64d6a97384a93dee78` =
`origin/develop`). This note carries **no `inventory-delta:` block**: it adds and
removes no tests; the tree is byte-identical to the starting head after this
round plus this note.

> This note carries **no `inventory-delta:` block**: it adds and removes no
> tests, and the gate reads an absent key as zero movement.

## Named CI gate: `test` — does not fail on this head

The lane named `test: failure` from a merge-queue evaluation, with prior
findings blaming `npm audit` (GHSA-68fv-2mgg-jv7q via `source-map-js@1.2.1`) and
untriaged `multidict`/`werkzeug` CVEs. All three are stale:

- `packages/hive-conductor/frontend/package-lock.json` pins
  `source-map-js@1.2.2` (bumped in `4fcb55d2a`); `npm audit --audit-level=high`
  exits 0 in **both** frontends (0 vulnerabilities, re-run this round).
- `uv.lock` pins `multidict==6.9.1` and `werkzeug==3.1.9` (the CVE'd 6.7.1 /
  3.1.8 are gone). Supply-chain gate re-run with CI's exact recipe
  (`uv sync --locked --all-extras`; `uv pip freeze --exclude-editable`;
  `pip-audit --strict`; `scripts/pip_audit_gate.py`): only the pre-triaged
  `ecdsa==0.19.2 PYSEC-2026-1325` remains; gate exits 0, direct-dependency
  usage check OK.
- The supplied dispatch snapshot's check-runs **on this exact head** (captured
  2026-10-06T13:46:18Z) show all 31 checks `success`, including `test` and
  `Supply chain (pip-audit)`; the newest `gates-ran` commit status (Actions run
  37469619959) is `success`.

Every `ci.yml` `test`-job step was re-executed locally at this head:

| CI step | Local result |
| --- | --- |
| `uv run pytest tests/ --ignore=tests/tools/registry` | 4533 passed, 122 skipped |
| hive-conductor backend tests | 3408 passed, 5 skipped (`uv run` venv; CI uses system python) |
| canvas + design + ext-sdk tests | 1154 passed, 76 skipped |
| turing + turing/backend + rsi + evolve tests | all pass; 3 initial `test_swebench.py` failures were Docker-socket-only and pass (315 passed) with `DOCKER_HOST=unix:///run/user/1000/docker.sock` |
| canvas frontend `npm ci && npm run test:ci` + lint + build | 79 passed; lint 0 errors; build ok |
| hive frontend `npm ci` + lint + build | lint 0 errors; build ok |
| OpenAPI types drift (`dump-hive-openapi.py` + `gen:api` + `git diff --exit-code`) | in sync |
| single-process cross-tree step (`tests/` + hive backend + design, `--timeout=60`) | 8588 passed, 128 skipped, 1 local-only failure, see below |
| `check-suite-inventory.py` (all 16 suites) + `check-test-duplicates.py` | ok / ok |

### Local-only failure, proven environmental (not repaired, recorded)

`packages/maistro-design/tests/test_importer.py::TestScanDesignSystemContent::test_plain_text_never_blocks`
failed only in the cross-tree run: Hypothesis replayed the counterexample
`text='jailbreak'` from this worktree's **gitignored** `.hypothesis/examples`
database. The word "jailbreak" is plain lowercase text and
`packages/maistro-core/src/maistro/security/patterns.py:88` blocks it by design,
so the property as written is over-strong. Both files are byte-identical to
develop (`git diff 1e640df17 fd2eddfa3 -- packages/maistro-design
packages/maistro-core/src/maistro/security/patterns.py` is empty), CI is green
on this head (fresh checkouts have no Hypothesis DB), and re-running the file
with a fresh database (`settings.register_profile(..., database=None)`,
`-p` plugin) passes 58/58. Not introduced by this branch; left untouched — a
genuine upstream test/product contradiction for develop, outside issue #42.

## Other gates re-run exactly

- `uv run ruff check .` / `uv run ruff format --check .` — pass.
- Exact vulture ledger command
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1332 reviewed identities ↔ 1332 findings, base
  `1e640df17c8a` → candidate `fd2eddfa3ad1`. **No ledger amendment needed**;
  none made.
- `check-execution-lifecycles.py` (19/19 classified), `check-foreign-harness-egress.py`
  (exit 0), `check-wiring-reads.py` (11 unread matched) — pass.

## Issue #42 acceptance — fresh executed evidence

- **Every physical execution has an Attempt.** `runs/execution.py:394`
  persists the Attempt (`create_attempt`) before launch and `:594` passes
  `execution_id=attempt.attempt_id` into `ExecutionRuntime.execute`; chat joins
  the same seam via `runs/chat_execution.py` (`RunExecutionService` with real
  `lease_ttl`). Canonical-path proof, not exhaustive reachability.
- **Retry creates a new chronological Attempt.**
  `runs/test_execution_is_correlated.py` and
  `graph/durable_runs/test_node_retry_attempts.py` pass (stable Run/NodeRun,
  new Attempt ordinals).
- **Canonical idempotency/effect contract (#1194).**
  `graph/durable_runs/test_ambiguous_effect_replay_guard.py` passes: ambiguous
  effects are not blindly re-executed across revisits. #1194 closed
  2026-09-29 (dispatch snapshot).
- **Cancellation/deadline cross the Runtime boundary (#1169).**
  `runtime/test_public_cancellation_fence.py`,
  `runs/test_attempt_cancellation_cause_model.py` pass; #1169 closed
  2026-09-13. Arbitrary external-provider behavior remains inherently
  untestable.
- **Chat lease/fence/reclaim + terminal-write recovery (#1170).**
  `runs/test_chat_attempt_recovery.py` passes; #1170 closed 2026-09-10.
- **No direct bypass on migrated core paths.** The three wiring gates above
  pass (no unread/undiscovered lifecycles, no foreign-harness egress).
- **Persistence/Events correlation across retries/recovery — now on live
  PostgreSQL** (the prior round's UNVERIFIED residual). Started
  `pgvector/pgvector:pg18` via the rootless Docker socket, migrated
  `alembic upgrade head` → **058**, and ran:
  `test_task_restart_recovery.py` + `capabilities/test_pg_invocation_store.py`
  + `test_pg_approval_store.py` + `test_pg_invocation_contention.py`:
  **33 passed, 0 skipped** (the worker-death restart E2E actually ran);
  `tests/persistence` + `test_container_postgres.py` +
  `tests/migrations/test_migration_chain.py`: **824 passed, 97 skipped**;
  `alembic downgrade base` + `upgrade head` reversible on the same database.
  Container removed afterwards; no repository or remote residue.
- **#1169/#1170/#1194 close first.** All three `closed` in the supplied
  dispatch snapshot (2026-09-13 / 2026-09-10 / 2026-09-29). No GitHub
  mutations performed.

## Residual risks

- #232 (M1-B2b, task Attempt recovery PostgreSQL worker-death proof) is still
  open; the issue text gates completion on #1169/#1170/#1194 only, all closed.
  The restart E2E now passes on live PostgreSQL, but continuous production
  soak is not proven here.
- The maistro-design property-test contradiction above is real on develop and
  will keep failing any local run with a polluted Hypothesis DB; CI is
  unaffected until Hypothesis's random search finds the same counterexample in
  a fresh checkout (astronomically unlikely at `max_examples=50`).
- Canonical-path Attempt coverage is proven at the seams and by the wiring
  gates; an exhaustive enumeration of every migrated caller is not mechanical
  and remains review-supported.

No dependency, ledger, grant, gate, or policy file was modified. No remote
mutation. Verdict for the repair lane: MERGE-READY (handoff only; not
integration approval).
