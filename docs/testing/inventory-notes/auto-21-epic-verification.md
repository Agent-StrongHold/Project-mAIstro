---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
  packages/maistro-evolve/tests: +0
---

# Epic #21 (M4-A governed candidate/evaluation/promotion loop) — verification record

Documentation-only verifier note at head `fa3391e5e925e342d6b2a244f29abe058b1b0c13`
(branch `auto-21`, identical to the develop base — zero epic commits exist in this lane).
No production or test code changed. No driver `check-*.log` files existed for this job
(manifest `checks: []`), so every check below was executed fresh.

## Executed at this head

- `uv run pytest packages/maistro-core/tests/graph/test_template_store.py
  packages/maistro-core/tests/graph/test_node_template_store.py
  packages/maistro-evolve/tests/test_population_audit.py
  packages/maistro-evolve/tests/test_rsi_safety.py -q`
  → **145 passed / 58 skipped** (skips are PG/service-gated).
- `uv run ruff check .` → clean. `uv run ruff format --check .` → 2669 files formatted.

## Acceptance status (epic = full chain with truthful evidence, no side path)

**What exists and works (partial):** an audited, policy-gated promotion API exists at
both the template and genome layers — `maistro/graph/templates.py::promote_audited`
(required `PromotionApproval`, attempt/commit audit ordering with a `promoting`
intermediate state; SPEC-081226-bb3a R14/AC-11) and
`maistro_evolve/population.py::promote_audited` (audit + `approved_for_promotion`
human gate). Their suites pass at this head.

**What fails acceptance:**

1. **#854 NOT satisfied at this head.** `PopulationStore.get_champion()`
   (`packages/maistro-evolve/src/maistro_evolve/population.py:116`) is an unfiltered
   max over `fitness_score`; `_promote`/`promote_audited`
   (`population.py:123,187`) check only approval + audit. Executable proof at this
   head: a genome with a **single** fitness sample (0.95) became champion over the
   0.90 active incumbent and `promote_audited` accepted it — `PipelineGenome` has no
   sample-count/evidence/uncertainty fields at all, and the word "incumbent" appears
   nowhere under `packages/maistro-{evolve,rsi}/src`. The fix exists on the
   **unmerged sibling branch `auto-854`** (commits `28a17a9b7`, `4d1a08f9b`,
   `4eb529b33`: `maistro_evolve/promotion.py` with `PromotionPolicy`
   min-samples/min-margin/objective-version pinning) but is **not reachable** here.
2. **#861 NOT satisfied at this head.** Conductor
   `services/optimizer.py:405-406` sets `applied = True` and counts `auto_applied`
   for AUTO_APPLY proposals **without executing any mutation** (the `_apply_*`
   helpers at `:533/:560/:647` run only from `record_decision:488`, and only for
   accepted KIND_TOPOLOGY) — fake-apply evidence, verbatim the defect #861 names.
   Accepted topology edits write `stores.dags[dag_id] = dag` in place (`:676`):
   no immutable candidate version, no content-hash binding, no `promote_audited`,
   prior version not addressable. `_apply_node_field_mutation` swallows conversion
   failures via `contextlib.suppress` (`:533-558`) so silent no-ops report as
   applied; `upgrade_execution_tier` self-stamps `tier_approved_by: "admin"`.
   Core-side, `maistro/graph/optimizer.py:285,326` `optimize()` returns a mutated
   `GraphConfig` copy directly. The fix exists on the **unmerged sibling branch
   `auto-861`** (`296d6e5a6`, `services/optimizer_candidates.py`) — not reachable here.
3. **#110, #112, #113, #115, #116: no implementation commits exist on any branch**
   (`git log --all --grep` per issue; hits were substring false-positives such as
   #1108/#1135/#1156). Specifically: no retrodiction prefilter anywhere
   (`git grep retrodiction` empty on HEAD, `auto-854`, `auto-861`); no candidate
   archive/historical-retention evaluation (only `get_lineage` exists); no
   generator/mutation/operator credit attribution (only node-level TextGrad
   attribution in `maistro_evolve/reflect.py`); no mechanical-vs-judgment promotion
   split (RSI has RLPHD judgment review only, `maistro_rsi/promotion_review.py`);
   no single canonical promotion contract shared across
   Evolve/prompts/skills/code/policy/harness artifacts.

## Verdict

NEEDS-REPAIR. The epic cannot be proven at this head: 2 of 7 children are
implemented on unmerged sibling lanes (`auto-854`, `auto-861`) and 5 of 7 children
have no implementation anywhere. Next: land auto-854/auto-861, then implement
#110/#112/#113/#115/#116 (or the #116 contract that absorbs them), and re-run this
record's battery against the merged head.

## CI-repair round at 7102397a73c32e3a59ac3dae6e14f2c0a5533e80 (2026-10-02)

Scope: the merge-queue gate failures named for this lane — `integration-scope`
and `docker-build` (CI runs 36833975017/36833974902) — plus the vulture
per-identity ledger instruction. No test added; inventory record only.

- **Root cause (docker-build):** the canary step's `DOCKER_BUILDKIT=1 docker
  build -f Dockerfile.rsi-runner` died in `RUN uv sync --python 3.12 --frozen`
  on `Failed to download alembic==1.20.0 ... network timeout. Try increasing
  UV_HTTP_TIMEOUT (current value: 30s)` after ~5 minutes of stalled/retried
  wheel downloads on the runner (job log, 08:11–08:17Z). Transient network,
  not a code regression: engine, hive-conductor, and every non-Docker job
  passed at the same head.
- **Fix:** `Dockerfile.rsi-runner` ENV gains `UV_HTTP_TIMEOUT=120` (uv's own
  remediation hint). `--frozen` is untouched, so lock drift still fails the
  build; only the per-request HTTP timeout is widened.
- **integration-scope** failed solely as the required-evidence aggregator
  (`docker-build is required by integration scope but concluded failure`, job
  log line 534); every other required specialized check succeeded. Fixing
  docker-build is the fix for integration-scope.
- **Local proof:** the exact CI canary step script (ci.yml:973-1085, extracted
  verbatim, run once per builder) passed under both `DOCKER_BUILDKIT=1` and
  `DOCKER_BUILDKIT=0`: build completed, positive control found the planted
  canary, and the filesystem/layer/history scans all reported absence; the
  image carries `UV_HTTP_TIMEOUT=120` and a working venv (`import alembic,
  maistro` OK). The step's cleanup trap left the worktree clean.
- **Vulture ledger:** `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0;
  1390/1390 findings classified, `unclassified: 0`, `never_allowlist: 0`. No
  unbanked identities exist at this head, so no dead-code removal and no
  `quality/vulture-baseline.json` amendment was required.
- Also green locally: `uv run ruff check .`, `uv run ruff format --check .`
  (2670 files), `scripts/check-build-context.py`, and
  `scripts/ci_merge_group_scope.py` confirms `Dockerfile.rsi-runner` maps to
  `docker_build: true` so the aggregator still requires (and now receives)
  docker-build evidence.
