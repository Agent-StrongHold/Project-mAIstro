# HANDOFF — #921 coverage-gate repair round (branch `auto-921`, head `2b3ab83cb1a9`)

Job `b05e9cc48749422ab655bc642dba6c68`, 2026-10-05. Scope: repair the red
**Coverage gate (publish-set floor + diff coverage)** at PR #1970 / head
`2b3ab83cb1a942931ccec3580188d2555906b60d` (base `8a4bc239fe9a`). No code change
was warranted; this file is the evidence record.

## What CI actually failed

Check-run `111592414135` (annotations: "Process completed with exit code 1").
Job step list (fetched from the Actions API):

| step | conclusion | completed |
|---|---|---|
| 6 download producer coverage data | success | 02:32:23 |
| 7 **combine** | **failure** | **02:56:50** |
| 8 diff coverage gate | skipped | — |

The combine step ran **24m27s** (historical: ~11m, per the comment block in
`.github/workflows/quality.yml`). A publish-set-floor failure aborts in the
first ~1–2 min of that step; dying at 24.5 min locates the failure in the
**late serial producers** (hive-conductor backend, then the root `tests/`
scripts producer) — not at the floor, and the diff step never executed.

## Local reproduction at this exact head (CI's exact commands)

Producer legs, in workflow order — all green:

- `maistro-server`: 494 passed, 8 skipped (61s)
- `maistro-turing` src: 210 passed; `maistro-turing/backend`: 90 passed
- `maistro-design`: 540 passed, 1 skipped
- `maistro-registry` + `tests/test_check_citation_status.py`: 257 passed
- `hive-conductor/backend`: run 1 → **1 failed** (`test_property_substrate.py::test_property_marked_field_is_immediately_locked`), 3337 passed; **run 2 → 3338 passed, 6 skipped**. Passes standalone. Transient.
- root `tests/` (scripts producer): run 1 → **2 failed** (`test_check_direct_dependencies.py::test_local_workspace_distribution_mapping_beats_editable_metadata_gap`, `test_check_merge_markers.py::test_this_repository_is_clean`), 4416 passed; **run 2 → 4418 passed, 90 skipped**. Both pass standalone. Transient.

Gate sub-checks:

- **Diff coverage**: `uv run python scripts/check-diff-coverage.py coverage.xml --base 8a4bc239fe9af429be9faa087916f965e9fb20f7` →
  `ok: every measured file this change touches is at or above 90% lines / 80% branch arcs`, exit 0. The diff's only Python file is the new rsi test, exempt by the gate's own `/tests/` rule; docs are not Python.
- **Publish-set floor**: structurally unreachable by this diff. The only publish-set producer the candidate touches is `packages/maistro-rsi/tests`. Measured twice at this head: `coverage report --include='packages/maistro-rsi/src/maistro_rsi/*'` = **5421 stmts / 420 miss / 1478 arcs / 91% — byte-identical with and without the new test file** (it imports no maistro module). All other publish-set suites/sources are untouched by the diff (`git diff --stat origin/develop...HEAD` = 3 docs files + 1 test file), so floor(HEAD) = floor(base) in any fixed environment. CI's own `coverage (no services)` / `(PostgreSQL)` / `(MinIO)` producer jobs were green on this head.
- **Vulture exact-debt-ledger** (lane brief): `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1338 reviewed identities = 1338 findings, exit 0. **No ledger amendment needed** — CI's `exact-debt-ledger` check was green too.

## Verdict of this round

The red is **not attributable to the #921 diff**. Every producer leg passes at
this head on rerun; the one CI red is consistent with the same transient
producer failures reproduced locally once each (hive-conductor
`test_property_marked_field_is_immediately_locked`; root-suite
`test_check_direct_dependencies` / `test_check_merge_markers` order-dependent
reads of ambient repo/venv state). No gate was weakened; no ledger edited; no
production code touched. The merge queue re-evaluates on enqueue.

## Residual risks (next repair round, only with reproduced evidence)

1. `hive-conductor/backend/tests/test_property_substrate.py::test_property_marked_field_is_immediately_locked` — flaked once locally, unreproduced since. Root-cause before touching.
2. Root-suite order-dependence: `test_this_repository_is_clean` and `test_local_workspace_distribution_mapping_beats_editable_metadata_gap` read ambient tracked-file/venv state and failed once in-suite, passing standalone and on suite rerun. Needs a captured failing log to bisect the polluter; a guessed "fix" would be cosmetic.

## Issue #921 acceptance (independent check)

- Benchmark: `packages/maistro-rsi/tests/test_m8c2_rerank_rewrite_benchmark_research.py`, 26 checks — driver run green; full rsi suite 994 passed at this head.
- Disposition: **WATCH** with INCUBATE/REJECT escalation criteria in `docs/research/921-reranking-query-rewriting.md` (lines 171–190).
- Inventory: `docs/testing/inventory-notes/921-m8c2-rerank-harness.md` (+26) and `check-suite-inventory.py --suite packages/maistro-rsi/tests` = ok (994).
