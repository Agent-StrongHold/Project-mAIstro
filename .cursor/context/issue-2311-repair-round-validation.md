# Issue #2311 repair-round validation evidence (auto-2311)

## What this round changed

- Merged `origin/develop` (tip `ae1cb3b17e`, PR #2475 #2464 Binding-scope work) into
  `auto-2311` to clear PR #2474's develop-tip conflict. One real conflict,
  `packages/maistro-server/src/maistro_server/canvas_runtime.py`: the #2311
  scope-stamped `CanvasImageBlobStore(store, workspace_id=…, project_id=…)`
  constructor call combined with #2464's `GovernedGatewayImageClient`
  `workspace_id`/`project_id`/`binding_id` kwargs. Both retained; resolution is
  the merge commit `c69acc13e3`.
- No source or test edits beyond the conflict resolution; no ledger amendments
  (all ratchets passed unamended); no new tests, so no inventory-note deltas.

## The failing gate, root-caused

CI run 44990323823 / job 137113679959 at `e340518af1` failed exactly one step:
`scripts/check-diff-coverage.py coverage.xml --base 33ac30c5f1` —

```
FAIL: packages/maistro-server/src/maistro_server/canvas_runtime.py:
77.8% of 9 changed lines (need 90%); uncovered 124, 126
```

Lines 124/126 were the TRUE branches of the `CanvasImageBlobStore.put` scope
stamping. Commit `c50cec0540` ("test: cover CanvasImageBlobStore scope metadata
stamping for diff-coverage gate") added
`test_put_stamps_canonical_scope_when_configured` for exactly those lines — it
landed after that CI run. The `RuntimeError: Event loop is closed` annotations
in the same log are `PytestUnhandledThreadExceptionWarning`s from an aiosqlite
connection worker in `test_tasks_run_identity.py` (teardown noise; the same CI
step shows `712 passed, 14 skipped` — the server producer passed). The
publish-set floor passed at 95% in that run.

## Local proof on the merged tree (CI-exact producer set)

Replicated the whole coverage-gate job against a local pgvector:pg17
(`postgresql://maistro:maistro@127.0.0.1:15911/maistro_test`; MinIO producer
legs ran on moto — a conservative under-measurement, no `--extra s3`):

- producers green: unit (core/canvas/evolve/rsi/bootstrap), archive (128
  passed), postgres (migrations 173, schema suites 7410, backlog 115, canvas
  649), server 720, turing 225 + backend 138, design 689, registry 366,
  ext-harness 273, ext-sdk 147, hive-conductor backend 4292, root/scripts
  6024.
- floor: `coverage combine` + `coverage report --fail-under=87` →
  `TOTAL 95058 3482 25246 1835 95%`, exit 0.
- diff gate: `coverage xml` +
  `python scripts/check-diff-coverage.py coverage.xml --base ae1cb3b17e` →
  `ok: every measured file this change touches is at or above 90% lines /
  80% branch arcs` (4 measured src files, 5 exempt test files), exit 0.

## Other gates re-run post-merge

ruff check / format --check: clean. `mypy --strict packages/maistro-core/src`:
Success (846 files; core src byte-identical to develop tip, so the pyright
ratchet baseline is untouched). vulture 1221=1221, radon 124=124,
reachability 82 unreachable all dispositioned, promotion surface ok, direct
effects 49 sites dispositioned, suite inventory 21 suites match
(`check-suite-inventory.py`), test-duplicates ok.

## Acceptance re-validation over real PostgreSQL

- `packages/maistro-server/tests/api/test_canvas_supported_path.py` with
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_REQUIRE_PG_LEGS=1`: 10/10 passed, including
  `test_generate_persist_retrieve_render_accept_over_a_restart` (the complete
  generate → durable scope-stamped blob → presentation URL → authorized GET
  with stored media type → accept_variant renders the persisted asset; also
  asserts the serialized `image_path` is `/v2/canvas/blobs/{id}` and not the
  raw UUID), `test_accepting_the_second_variant_still_serves_its_own_bytes`,
  `test_a_foreign_principal_and_a_guessed_id_read_absence`.
- `packages/maistro-server/tests/api/test_canvas_scope_postgres.py` over PG:
  4/4 passed (#2464 Run → Attempt → Binding → Invocation identity/scope,
  restart, concurrent tenants, mismatched-Binding refusal) — asset and
  Run/Invocation answer to one Workspace and Project.
- Runner startup/restart/Binding regressions: 8 passed; external-worker
  opt-out (`CANVAS_SERVER_CONSUMER_ENABLED=false` gates the start, default on):
  11 passed in `test_main.py`.
- In-repo frontends consume no `/v2/canvas` image_path (the canvas UI consumer
  is downstream), so the browser `img src` contract is pinned at the HTTP
  boundary the E2E proves: a real GET-able URL serving exact bytes with the
  stored media type under Workspace-member auth, `Cache-Control: no-store`.
