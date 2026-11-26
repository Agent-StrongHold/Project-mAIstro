# #2059 repair round — exact-head validation log (2026-11-18)

Lane CR2059, job `d2bff8056a2e4647968cffaae18fd9b7`.
Head: `4f5408b8e46f0aa6be449180398d0cd2a7379be1`
(= PR #2059 head; = `3933b42ed2` + develop merge `377679dd81` (d0e8e235a8,
#2120 node:26-alpine) + test-contract sync `4f5408b8e4`). Base:
`d0e8e235a896d2644b33852f64cbdca1766ec59e` (= merge-base, so the branch is
fully synced with develop). This file supersedes
`.cursor/context/2059-repair-3933b42-validation.md` for everything after that
head. No production code changed on this branch between `3933b42ed2` and this
head — only `tests/test_check_required_checks.py` (4-line contract sync) and
the develop merge — so every gate re-proven here covers both heads.

## Why this round exists

The previous verify job (`7a2d321ab5264c479d26901868d65dfe`) died on a
provider 404 before validating anything; its only completed checks were
`uv sync`, `ruff check .`, `ruff format --check .` — all exit 0. The lane
brief repeated the "CI response truncated" merge-queue failure block and the
vulture-ledger repair instruction, so every RED-list gate was re-proven at
this exact head rather than inherited.

## Local replays at the exact head (CI-exact or CI-shaped)

| Gate | Invocation | Result |
|---|---|---|
| sync | `uv sync --locked --extra dev`, then CI-shaped `uv sync --locked --all-extras` + `uv pip install -e packages/maistro-evolve` | OK |
| Ruff | driver check-1/check-2 logs + re-run | exit 0 |
| exact-debt-ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 — **1236 reviewed identities -> 1236 findings**, base `d0e8e235a896`. No unbanked identities; the instructed ledger amendment is a no-op, none made |
| Acceptance state | pgvector:pg18 `cr2059-acstate-pg` @127.0.0.1:55433 (POSTGRES_USER/PASSWORD/DB = maistro/maistro/maistro_test, same as CI's service) + `alembic upgrade head` (exit 0, at head) + `RATCHET_BASE_REV=origin/develop MANDATE_BASE_SHA=d0e8e235a896… uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate d0e8e235a896…` | **exit 0** — design_coverage measures **44.4608% over 166 taken decisions, exactly on the bank** (`quality/ac-state-notes/fix-vulture-single-owner-1357.json`); 10 debt counters sit exactly on ceilings, folded from 49 notes; mandate 0 added/unproven; chain mandate clean |
| Coverage / diff gate | root producer CI-exact: `env -u DATABASE_URL -u MAISTRO_TEST_PG_DSN uv run coverage run --branch --source=scripts -m pytest tests/ tests/test_model_check_consumer_claim.py packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30 -q` then `coverage xml` | **6072 passed, 139 skipped, 0 failed** (12m46s); `check-diff-coverage.py coverage.xml --base d0e8e235a896…` exit 0 — 2 changed files measured (scripts/check-gates-ran.py, scripts/check-required-checks.py) at/above 90% lines / 80% branch arcs; 11 changed test files exempt by declaration |
| suite inventory | `uv run python scripts/check-suite-inventory.py` | exit 0 — 21 suites match, 35,626 unique identities (grew from develop's 35,599 by this branch's noted tests) |
| backlog | `check-backlog-consistency.py` | exit 0 |
| agent store writes | `check-agent-store-writes.py` | exit 0 |
| contract markers | `check-contract-markers.py` | exit 0 |
| convergence matrix | `check-convergence-matrix.py` | exit 0 |
| BFCL/IFEval provenance | `vendor_bfcl.py --check`, `vendor_ifeval.py --check` | exit 0 both |
| ratchet provenance | `check-ratchet-provenance.py` | exit 0 |
| shipped surfaces | `check-shipped-surface-truth.py` | exit 0 |
| Architecture fitness | `PYTHONPATH=packages/maistro-core/src uv run pytest packages/maistro-core/tests/fitness -q --timeout=30` | 39 passed |
| touched envelope | `pytest tests/test_check_gates_ran.py tests/test_gates_ran_merge_group_scope.py tests/test_check_required_checks.py tests/test_ci_vulture_ownership.py tests/test_devskim_scan_scope.py` | 268 passed |
| floor/contract tests | `pytest tests/test_cpython_base_grype_floor.py tests/test_docker_cli_vendored_advisory_floors.py tests/test_temporalio_bridge_zip_floor.py tests/test_distribution_contract.py tests/test_restore_oracle_characterization.py tests/test_restore_oracle_readiness_gate.py` | 44 passed |
| paths-filter contract | shipped `.github/workflows/mutation.yml` pull_request paths contains `quality/image-pins.json` (develop's #2120); `tests/test_check_required_checks.py` synced to it at `4f5408b8e4` | verified in-tree |

Coverage-gate publish-set floor (87%): not replayed locally — it needs the
`coverage-unit`/`coverage-archive`/`coverage-postgres` producer artifacts. The
branch's diff vs base contains **no file under any MEASURED_ROOTS source tree
except `scripts/`**, and `scripts/` is scored by the diff gate above; the
publish-set statement set is therefore bit-identical to the base revision,
whose hosted Coverage-gate run was green at `3933b42ed2` (122 check runs, 0
failures — see the `3933b42` note). Inherited, not re-measured.

## Findings resolution (this round)

1. **"design_coverage non-reproducible bank" (carried prior finding) —
   REFUTED at this head with the full CI shape.** The earlier unstable values
   (39.86 / 44.39 / 44.23) came from incomplete-environment replays. With
   CI's exact shape (pg18 DSN, alembic at head, all extras, maistro-evolve
   installed) the measured value reproduces the banked 44.4608 exactly at
   `4f5408b8e4`. Bank is sound; no ledger edit made.
2. **Vulture ledger repair instruction — no-op.** The exact-argument gate
   reports zero unbanked identities at this head; `quality/vulture-baseline.json`
   was not touched.
3. **New local-environment hazard (documentation only, no code change).**
   `check-ac-state.py` writes gitignored `quality/ac-state.json` into the
   workspace. A shared long-lived worktree that keeps that file makes
   `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
   fail with `unclassified quality state: quality/ac-state.json`. CI is
   immune (fresh checkout per job), and the file is untracked — move it aside
   before local root-suite runs. Confirmed: test passes once the artifact is
   removed; root producer re-run green.
4. **Issue-body prose staleness** ("1,328 identities", "5,066 cases", draft
   status, "sole semantic workflow change" vs the pinned-CPython bump):
   still stale, prose only — GitHub mutations are out of scope for this lane.
   The gate facts behind them (vulture ledger, suite inventory) are green as
   measured above.
