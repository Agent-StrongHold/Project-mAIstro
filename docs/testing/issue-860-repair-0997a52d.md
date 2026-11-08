# Issue #860 repair checkpoint — 0997a52d

## Frozen scope

- Issue: #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `c4e9285f8edb6f2a3ee4582715b01f4a0839635a`; supplied base: `675db8be6c41b020ffffb224b2748c159c78a122`.
- Starting worktree clean; no incoming edits to salvage.
- Inputs: supplied dispatch-context.json, prior result e62cdc6f, prior failed check-3.log from 98a11313. No check-*.log files were supplied in the current job directory.
- Frozen repair candidates: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, its adjacent `tests/persistence/test_pg_learnings.py`, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `quality/vulture-baseline.json` (only for observed CI scanner debt), an inventory note if tests change, and this report.
- Read-only context: repository instructions, relevant ADRs, soak profile/evidence, server limiter path and adjacent tests, CI gate definitions.

## Initial evidence and assumptions

The supplied failed schema check expected 21 DDL statements and observed 24. This is historical evidence, not proof of a failure at the assigned HEAD. The prior result reports that failure already repaired and exact-RC promotion blocked. Reproduce both claims before making any repair. No unresolved refs, network refresh, GitHub mutations, deployment promotion, or alternate runtime authority are authorized.

## Reproduced CI targets

- `uv sync --locked --extra dev`: passed (256 resolved, 214 checked).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. Historical failure is not reproducible: the independent expected-DDL list at lines 174–178 already includes all three Gauntlet columns. Skips do not prove live PostgreSQL behavior.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, **1326 findings / 1326 reviewed identities**, zero unclassified and zero never_allowlist. Scanner selected trusted base `e46ad6708fda`. No unbanked identities exist; no ledger edit is justified.

The two dispatched CI targets are finished: both pass at the exact starting HEAD. Do not manufacture a code/test/ledger change.

## Architecture and acceptance inspection

Read AGENTS.md, docs/README.md, and accepted ADR-087 (schema expansion), ADR-081626-f383 (Attempt leases/fencing), ADR-082426-82c7 (occurrence admission), ADR-085 (principal rate limits), and ADR-083026-a91e (unmeasured metrics). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: admission uniqueness does not prove physical execution uniqueness; process exit does not prove lease recovery. ADR-085 does not waive replica-selection resistance. No competing authority or policy change is proposed.

The current schema fence encloses all upgrade DDL in one transaction; its independent expected-DDL regression now includes the Gauntlet audit columns. The frozen profile calls the soak driver a host-process preflight, explicitly excludes representative user/Workspace, Graph, successful model/tool and Design/Canvas traffic, and admits Goal/recovery/telemetry gaps. `run_soak.py:730` always rejects exact-RC equivalence. `test_soak_promotion_gates.py:439` exercises production limiter instances and expects independent allowances on each replica; `api/rate_limit.py:32` explicitly documents N-times aggregate budget. These are blockers, not reasons to invent new acceptance semantics.

## Additional executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3195 files).
- `uv run pytest packages/maistro-core/tests/persistence -x -q`: **604 passed, 290 skipped**, 27 SQLite datetime-adapter deprecation warnings. No live PostgreSQL proof claimed.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **74 passed**. Covers production limiter instances, degenerate admission probes, real subprocess sampling, CLI preflight rejection and task backpressure.
- Imported current `scripts/soak/run_soak.py` using `uv run python` and called `failed_promotion_checks` on frozen `evidence/m3a-round30-shakedown.json`: asserted exactly `['sustain_duration', 'exact_rc_artifact']`. Observed **420.08 s < 14400 s**, topology **host-uvicorn-preflight**, reason **not the exact production Compose image and configuration**. Also asserted `preflight_artifact_check()['ok'] is False`. This is fresh evaluation of historical evidence, not a fresh deployed soak.
- `uv run python scripts/check-ratchet-provenance.py`: passed (52 quality JSON consumers and delegated gates). Existing syntax/local HTTP CORS warnings did not fail it.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed.

No tests changed; no inventory delta required. No speculative scanner, source or gate repair made.

## Acceptance disposition

| # | Acceptance criterion | Evidence / result |
| --- | --- | --- |
| 1 | Representative RC profile | **UNVERIFIED complete**: inspected `m3a-load-profile.md:152` explicitly lacks multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal-worker traffic. |
| 2 | At least two deployed replicas | **UNVERIFIED for RC**: two-instance ASGI tests passed, but those are not deployed immutable images. Runner explicitly uses host processes. |
| 3 | Sustained saturation, reclaim, retries and leaks | **UNVERIFIED**: current evaluator rejects historical 420.08 s versus 14400 s minimum. Sampler tests cannot prove long-window production behavior. |
| 4 | No duplicate physical work; Goal reconciliation | **UNVERIFIED**: admission negative tests passed; profile records schedule probe cancels queued Run without execution. No sustained production Attempt/Goal workload executed. |
| 5 | Rate/security/degraded behavior resists replica selection | **UNVERIFIED as a whole; independent allowances reproduced**: both authenticated and unauthenticated production-middleware tests receive `[200, 200, 429]` on each replica for the same identity. Six-path local rejection is not a shared budget. |
| 6 | Complete telemetry and explicit thresholds | **UNVERIFIED**: sampler tests passed; profile admits missing application-loop, detached-worker, saturation/reclaim and long-window measurements. Driver loop lag is not application-loop lag. |
| 7 | Active-work kill/restart, drain, fencing and recovery | **UNVERIFIED**: boot/cleanup regressions passed; no physical in-flight Attempt recovery drill executed. |
| 8 | Long soak of exact RC artifact/config; rerun on changes | **BLOCKED / UNVERIFIED**: executed evaluator rejects duration and artifact. Longer execution of this preflight cannot establish production artifact equivalence. |
| 9 | Findings filed/reclassified at earliest broken invariant | **UNVERIFIED complete**: inspected historical human evidence classifies findings and includes outstanding external filing instructions. No GitHub mutation authorized or performed. |
| 10 | Published machine/human evidence tied to exact hashes | **Partial historical evidence only; exact-RC publication UNVERIFIED**: inspected both formats and reevaluated machine evidence; artifact/duration checks reject promotion. |

## Handoff

**BLOCKED for #860 acceptance.** Both dispatched CI repair targets already pass; no new failing check justifies modifying the ledger or production code. This report is the only changed file. Existing evidence and all source/tests/gates remain intact. No merge, push, service startup, background command, or GitHub mutation performed. Full-tree pytest deliberately not run.

Next prerequisite: select immutable RC images and complete runtime configuration for #89; complete the representative production-path workload/telemetry; reconcile replica-selection protection; execute at least the four-hour profile with correlated physical Attempt fencing/recovery. Another identical CI-repair dispatch or short host-process run cannot satisfy those missing acceptance criteria.

Progress: `{checked: 3, done: 2, skipped: 1, errors: 0, next: exact-RC acceptance}`. Skipped item: a fresh deployed RC soak; acceptance inspection was completed. Commit this report locally as a blocked handoff, never integration approval.
