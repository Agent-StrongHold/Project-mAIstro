# REPAIR-NOTES-2465 — round 2 (verification + diff-coverage repair)

Branch `auto-2465`, started at `7e00a4aa818427813399b24160c7bd4676aa362b`
(the PR #2492 head for issue #2465), develop base `c810c956785b156f6f328af3383b5b6ac3eaa72a`.

## What the previous block left unresolved

The prior repair job recorded `MERGE-READY` but committed nothing; the driver
flagged "worker made no commit; clean tree is not proof of repair". This round
independently re-verified every acceptance criterion and addressed the one gap
that real evidence exposed.

## Round-2 finding (actual evidence, not a scanner guess)

The quality.yml diff-coverage gate **fails** on the PR head when run with the
PR's base (`c87dd79acd`, the base recorded on PR #2492):

```
FAIL: 1 file(s) below the diff-coverage floor
  packages/hive-conductor/backend/routes/design.py: 57.1% of 7 changed lines
  (need 90%); uncovered 350, 439, 476
```

Three of the six re-anchored Design generic-500 branches (skill listing,
discovery form, render job creation) were bounded in code but never exercised
by a test. The prior round's acceptance claims did not include a
diff-coverage run, so this was never observed.

## Repair

`packages/hive-conductor/backend/tests/test_dag_failure_public_projection.py`
(+3, total 17): sentinel regressions for the three uncovered branches —

- `test_skill_listing_500_names_the_kind_not_the_catalog_detail` —
  `GET /design/skills` generic 500 keeps the "Skill listing failed" operation
  name and the exception kind (`ValueError`), never the catalog detail;
- `test_discovery_form_500_names_the_kind_not_the_engine_detail` —
  `GET /design/skills/{slug}/discovery` generic 500 (the classified 404
  `SkillNotFoundError` branch keeps its own documented shape);
- `test_render_creation_500_names_the_kind_not_the_store_detail` —
  `POST /design/projects/{id}/render` generic 500 (the 404/501 classified
  branches keep their shapes).

Each asserts the bounded detail text, the exception kind, and that the four
evidence sentinels (bearer-token provider reply, filesystem path, diagnostics
dump with internal host credential) never appear.

`docs/testing/inventory-notes/auto-2465-nested-dag-failure-projection.md`
updated: `inventory-delta: +17`, round-2 section added.

## Validation evidence (this round)

| Check | Command | Result |
|---|---|---|
| New sentinel regressions | `uv run pytest packages/hive-conductor/backend/tests/test_dag_failure_public_projection.py -q` | 17 passed |
| Full changed-package suite | `uv run pytest packages/hive-conductor/backend/tests -q` | 4357 passed, 46 skipped |
| Canonical lifecycle / receipts / composition (untouched pins) | targeted pytest | 49 passed |
| Graph runner + projection authority + design routes | targeted pytest | 98 passed |
| Ruff | `uv run ruff check .` / `uv run ruff format --check .` | clean |
| Suite inventory | `uv run python scripts/check-suite-inventory.py` | ok: 21 suites match |
| Vulture ledger (CI-exact args) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1221 reviewed = 1221 findings |
| Promotion surface / reachability / radon / security inventory / shipped-surface truth / direct effects / public routes / route permissions | respective `scripts/check-*.py` | all ok |
| **Diff coverage (the failing gate)** | `uv run coverage run --branch --source=packages/hive-conductor/backend -m pytest packages/hive-conductor/backend/tests --timeout=30 -q` + `coverage xml` + `uv run python scripts/check-diff-coverage.py <xml> --base c87dd79acd` | **ok: every measured file at or above 90% lines / 80% branch arcs** |

## Acceptance criteria re-verification (issue #2465)

1. **Single safe-projection policy, top-level and nested** — verified in
   source: one module (`services/safe_projection.py`) serves the receipts
   (`routes/dags.py::_public_result` on `run_dag`/`run_champion` and on the
   recorded projection), the streaming projection
   (`graph_runner._node_frames`, `_replay_stream`, `execute_dag_streaming`
   settle paths, `_failed_terminal`), the chat failure answer
   (`chat_completion.py` `public_failure(exc)`), and Design's generic 500s.
   No other transport projects an unprojected DAG result (all `execute_dag`
   callers swept; `substrate_tools`/`chat` preview read only seam-projected
   node responses and never copy the top-level `error`).
2. **Canonical evidence preserved** — `routes/dag_runs.py` imports nothing
   from `safe_projection`; `dag_run_inspection.visible_run_detail` still
   overlays canonical Run/NodeRun/Attempt/Event truth (the #1877 authorized
   overlay); `test_dag_run_canonical_lifecycle.py` passes unchanged.
3. **Sentinel endpoint regressions** — 4 evidence classes asserted absent
   from every nested field on receipt, champion, websocket/SSE frames,
   recorded SSE events, and the projection seam.
4. **Truthful status/run ids, 429+Retry-After, bounded kinds** — pinned by
   the receipt/admission/kinds tests; `HOST_AUTHORED_RUN_ERROR_CODES` matches
   exactly the 7 host-authored `error_code=` sites in
   `maistro/graph/durable_runs/*` (the 8th, `PhysicalExecutionError`, is
   correctly excluded — exception-derived, so bounded);
   `executor.py:1393` composes `f"{error_code}: {sanitize_failure_message(...)}"[:512]`,
   which is the format `public_failure_text` parses. Live `node_failed`
   progress events carry identity only (`legacy_dag_node.py:862-873`).
5. **No generic raw `str(exc)` on the finding surfaces** — Design's six
   generic-500 branches all answer `public_failure(e)` now, each pinned by a
   test; remaining `str(e)` in `design.py` are classified 404/400 domain
   errors. Pre-existing raw-text returns in routes outside #2465's finding
   surfaces (e.g. `validation_gate.py` proposal reasons served by the
   optimizer route, `chat_completion` tool-error returns, various 413/503
   classified handlers) are documented residuals, not this issue's scope.
6. **Inventory + required CI** — inventory note `inventory-delta: +17`
   accepted by `check-suite-inventory.py`; the diff-coverage gate now passes
   (see table); vulture/radon/promotion-surface/reachability/direct-effects/
   security-inventory/shipped-surface-truth gates all pass.

## Residual observations (not blockers, recorded for the M2 track)

- `services/validation_gate.py:44,53,212` put raw `str(e)` into proposal
  `reason` fields that the optimizer route returns to clients — same
  disclosure class, different route, pre-existing, outside #2465's named
  sources.
- `services/chat_completion.py` classified-domain tool-error `str(e)`
  returns (lines ~2117-3159) — pre-existing, outside the finding surfaces.
- The chat failure branch records the raw `exc.result` into the projection
  row's `result`; harmless because the HTTP detail overlay re-reads canonical
  truth (`_canonical_projection`), but a future consumer of the raw stored
  result would bypass the projection.

## Branch relation

`auto-2465` is 2 commits behind `origin/develop` (`c810c956` canvas/ADR
files); zero file overlap with this PR's touched paths, so no develop-sync
conflict existed to resolve — verified with `git diff --numstat` between the
merge-base sides.
