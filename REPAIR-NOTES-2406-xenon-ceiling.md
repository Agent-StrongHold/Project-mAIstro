# REPAIR-NOTES-2406 — xenon ceiling follows the banked radon improvement (#2311 cutover)

## Evidence (CI job 135146261446, head 8abbc978)

PR #2406's required `test` check failed at head `8abbc978` after 12m27s with
exactly one test failure:

```
FAILED tests/test_complexity_gate_scope.py::test_xenon_block_ceiling_equals_the_radon_ledger_length
AssertionError: XENON_BASELINE (126) diverges from the radon ledger's length (124).
```

Cause: the #2311 ADR-045 cutover retired `maistro_canvas/canvas/tool.py` and
pruned its two radon ledger rows (`execute_canvas` E 32, `_generate_image`
C 11) in the same PR — but `XENON_BASELINE` in `.github/workflows/quality.yml`
stayed at 126. The repo's own pin test
(`tests/test_complexity_gate_scope.py::test_xenon_block_ceiling_equals_the_radon_ledger_length`)
requires the ceiling to follow the ledger down **in the same PR**; it failed on
every head of this PR (the radon prune landed in the first commit). Everything
else in the captured rollup was green (75 success / 3 skipped), including the
server suite step whose "Event loop is closed" annotations are only a
`PytestUnhandledThreadExceptionWarning` from an aiosqlite worker thread —
that step passed (678 passed, 11 skipped).

## Repair (2 files, precedent #57 = commit 76e8472d36)

1. `.github/workflows/quality.yml`: `XENON_BASELINE: 126 -> 124`, with the
   conventional ledger-follow comment (the same convention as every prior
   move documented inline: 127 -> 126, 128 -> 127, ...).
2. `tests/fixtures/ci_quality_obligations.json`: the `quality-xenon` step's
   recorded sha256 updated to the new step digest
   (`117adc0f920e...d97cf9acc8`) — the obligation inventory pins step content,
   and #57 set the precedent of updating it in the same PR as the ceiling.

No test was added, removed, or renamed; no collected node ID changed, so no
suite-inventory delta applies.

## Re-measured xenon at head (CI-exact invocation)

`xenon --max-absolute B --max-modules B --max-average A -i third_party` over
the ten shipped `packages/*/src` roots: **124 block identities matching the
radon ledger one-for-one, rank for rank** (set-compared, 0 either way); module
axis 0 violations vs an empty `XENON_MODULE_LEDGER`; project-average axis 0
violations. 124 <= new ceiling 124 — the gate stays green.

## Validation (all exit 0 locally, RATCHET_BASE_REV=origin/develop)

- `pytest tests/test_complexity_gate_scope.py tests/test_ci_quality_split.py` — 101 passed
- `pytest tests/ --ignore=tests/tools/registry -q` (the failing CI step) — 5834 passed, 139 skipped
- cross-suite leakage step (`pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60`) — 10804 passed, 168 skipped
- `pytest packages/hive-conductor/backend/tests -q` — 4214 passed, 29 skipped
- canvas frontend: vitest 84 passed, lint 0 errors, build ok, `npm_audit_gate.py` OK (0 advisories)
- hive frontend: lint 0 errors, build ok; OpenAPI `types.gen.ts` regenerated with zero diff
- `ruff check .`, `check-workflow-inventory.py`, `check-test-duplicates.py`,
  `check-ratchet-provenance.py` (55 consumers, provenance OK), suite-inventory
  (canvas 628 / server 689) — all green
- Lane suites (unchanged by this repair, re-checked earlier in the round):
  canvas 628 + server 689 collected; `pytest packages/maistro-canvas/tests
  packages/maistro-server/tests -q` = 1252 passed, 85 skipped, 0 failed
- Live default-compose verification (fresh image built from this tree at this
  head): engine healthy, `/v2/canvas/designs` 200 over the wired
  `PgCanvasStore`, `canvas-image-gateway` Binding row present, and an inserted
  `generation_jobs` row claimed and executed by the in-process runner
  (pending -> attempts 1/2/3 -> failed with the fail-closed empty model
  registry — the documented no-registry behavior; no worker container in the
  project, so the engine process is the claimer).
