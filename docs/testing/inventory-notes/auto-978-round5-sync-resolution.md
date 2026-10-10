---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-978: round-5 develop sync (M9-B #2094) resolution + stale whitelist import

Repair round for #978 in `/home/dev/Git/wt/auto-978` (branch `auto-978`).
No test nodes were added or removed by this round's own edits — the
recorded suite inventory is unchanged and
`scripts/check-suite-inventory.py` passes. The develop sync itself added
test nodes, but those arrive with develop's own inventory notes
(`1882-pg-root-preparation-seam.md`, `1883-pg-run-insert-connection.md`,
`954-extension-post-install-lifecycle.md`), already reflected in the
baseline this branch merges.

## 1. Develop-sync conflict resolution (the preserved merge)

The worktree carried an in-progress merge of `4aa68edc0` (M9-B EPIC
#2094, "governed extension registry, discovery, signing, and install
lifecycle") with six unmerged paths. All six were resolved in place and
committed as `24a50ac8a`; `origin/develop` had since advanced two
further commits (`d11368cd7`, `bb4257f09`, the #1845 PG Run-insertion
work), and merging that tip produced no conflicts (`c3bcc09c7`). The
resolutions:

- `packages/maistro-core/src/_vulture_whitelist.py` — keep the branch's
  `SqliteExtensionHealthStore` import (referenced by the health-evidence
  whitelist entries); DROP the `from maistro.extensions.service import
  ExtensionInstallService` line. Taking "both sides" here was wrong:
  develop's M9-B deliberately removed that import together with the
  stale `ExtensionInstallService.enable`/`.set_pinned` whitelist refs it
  had annotated (the merged service API no longer has those verbs), so
  re-adding the unused import is a ruff F401 — which this branch's tree
  failed at the dispatched head. The whitelist now matches develop's
  post-#2094 state plus the health-twin import.
- `packages/maistro-core/src/maistro/extensions/__init__.py` — the
  `__all__` conflict keeps all three names in the package's grouped
  sort: the branch's health enums (`ObservationOutcome`,
  `OperatorDecision`) and develop's `OwnedResourceJanitor`, all present
  in the merged import block.
- `packages/maistro-server/src/maistro_server/api/extensions.py` — the
  types import keeps the branch's health/ranking views
  (`OperatorDecision`, `RankingMetric`, `SloPosition`) and develop's
  `RollbackRefused`; the handler `__all__` keeps the branch's
  `decide_extension_operator_state`/`export_extension_telemetry` and
  develop's `disable_extension` (all three exist as handlers in the
  merged module; `test_all_covers_every_route_handler` pins the list).
- `packages/maistro-core/tests/extensions/test_cli_certification.py`,
  `test_cli_compat.py` — comment-only conflicts (both sides describe the
  same whitespace-flattening assertion); kept the branch's wording.
- `quality/shipped-surface-truth.json` — the `backend_surfaces` conflict
  is a pure union: the branch's
  `POST /extensions/health/{extension_id}/operator` row ahead of
  develop's six #954 lifecycle rows (pin/unpin/disable/resume/rollback/
  remove). 231 + 6 rows; every other key is byte-identical between the
  sides. `scripts/check-shipped-surface-truth.py` passes.

## 2. Validation evidence for this round

- `uv run ruff check .` — clean (after the F401 fix above).
- `uv run ruff format --check .` — 3273 files already formatted.
- `uv run mypy <ci.yml's ten package srcs>` — "Success: no issues found
  in 1050 source files" (after `uv sync --locked --all-extras`; the
  standalone core+server invocation's six missing-stub errors are the
  documented minimal-venv artifact, gone under CI's exact command).
- `uv run pytest packages/maistro-core/tests -q` — 15215 passed, 1040
  skipped, 3 xfailed.
- `uv run pytest packages/maistro-server/tests -q` — 557 passed, 8
  skipped.
- `uv run pytest tests/ packages/maistro-core/tests/extensions/test_lifecycle_proof.py -q`
  (the root coverage producer's suite) — 5075 passed, 129 skipped.
- Coverage producers for every changed measured tree (core, server,
  scripts) combined to 92% total; `scripts/check-diff-coverage.py
  coverage.xml --base bb4257f09` — ok at the 90% lines / 80% branches
  per-file floors (health.py 97.7% lines / 93.8% branches;
  sqlite_health_store.py 99.2% / 94.4%; api/extensions.py 100%/100%).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1323 reviewed identities, exit 0.
- `scripts/check-reachability.py`, `check-reachability-dispositions.py`,
  `check-shipped-surface-truth.py`, `check-durable-table-inventory.py`,
  `check-merge-markers.py`, `check-suite-inventory.py` — all exit 0.
