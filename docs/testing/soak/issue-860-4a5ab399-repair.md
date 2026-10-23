# Issue #860 — repair job 4a5ab399

## Frozen scope and initial state

- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `a1dc9eac945a28d734723f61e3c54030c08d13fe`.
- Base supplied: `33bcd3ce28830032403e23ce82de8ccfaca2acce` (resolved by git diff).
- Initial worktree clean; no incoming diff to salvage.
- Single assigned item: #860, including the explicitly requested exact-debt-ledger CI repair. No GitHub mutations.
- Inspection snapshot: `scripts/soak/run_soak.py`, `scripts/soak/nginx-soak.conf`, `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`, `docs/testing/soak/m3a-load-profile.md`, `docs/testing/soak/m3a-soak-evidence.md`, the four existing evidence JSON packs, `packages/maistro-server/src/maistro_server/api/rate_limit.py`, task admission/backpressure tests, PostgreSQL learning-store tests, production Compose configuration, `scripts/check-vulture-baseline.py`, and `quality/vulture-baseline.json`. Relevant architecture and inventory policy are read-only context.
- Planned edits: this report; only scanner-confirmed retained identities in the ledger or genuinely dead code if found. No speculative runtime repairs or replacement execution authority.
- Prior job result read: b3784ba210e84166912b64e5460999f0 reported BLOCKED. Those claims will be rechecked, not adopted as proof.
- Driver logs: supplied job directory contains no `check-*.log` files; not found, skipped. Writer validation will run locally.
- Ambiguity: no new RC artifact/configuration is supplied. Assume the committed load profile and evidence packs define the available candidate evidence; do not invent a promoted artifact or assert a host preflight is a Compose soak.

## Validation and disposition

Exact-debt gate executed successfully (exit 0): 1370 findings / 1370 reviewed identities, zero unclassified and zero never-allowlist findings. Log: job directory `writer-vulture.log`. No ledger amendment is warranted: no new retained or eliminated identity was observed. This resolves the requested CI check, not the soak acceptance.

Architecture inspected: accepted ADR-085 (canonical principal rate limit), ADR-081626-f383 (Attempt authority/fencing), ADR-082526-b36a (heartbeat and reclaim), and ADR-082426-82c7 (occurrence identity). ADR-081 is **Proposed**, not accepted. The production reference Compose declares two application services; that declaration alone is not executed replica evidence. Reconciliation: retain Goal → Graph → Run → NodeRun → Attempt and the canonical limiter/resolver; admission uniqueness cannot substitute for physical-work fencing, and process-local enforcement cannot substitute for #860's replica-selection non-bypass requirement.

Current profile/evidence docs already retract the earlier shared-limiter claim and explicitly reject host preflight as exact-RC evidence. No cosmetic repetition or speculative runtime change is warranted. Focused validation passed: `uv run ruff check .`; `uv run ruff format --check .` (2725 files); and the PostgreSQL-learning/backpressure/soak-gates/production-boot test selection (88 passed, 5 PostgreSQL-dependent tests skipped because no test DSN was configured). Logs are `writer-ruff-check.log`, `writer-ruff-format.log`, `writer-pytest.log` in the job directory. Re-evaluating the four frozen historical evidence packs with the current `failed_promotion_checks` rejects every pack for both duration and exact artifact (`writer-evidence-audit.json`).

A suspected credential-shape defect was **disproved**, not repaired: `main_async` sends the complete settings entry as Bearer, but the canonical `api/auth.py:_build_token_index` explicitly accepts both full-entry and secret-only forms. The first ad-hoc import command failed with `ModuleNotFoundError: maistro_server` (the root uv environment does not install that member); rerunning with `PYTHONPATH=packages/maistro-server/src` resolved the existing source. Both forms resolved to principal `soak` (`writer-auth-validation.log`, exit 0). No auth code or test change is justified. This check is not multi-replica security proof.

## Executed commands

All validation commands were allowed 1200 seconds; none ran in the background.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, exact identity ledger unchanged.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 2725 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` — 88 passed, 5 skipped in 87.59 seconds. Skips at `test_pg_learnings.py:766,877,896,906,917` require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation is claimed.
- `uv run python` evidence audit — imports the actual `scripts/soak/run_soak.py` evaluator; loads the four frozen JSON packs; asserts both `sustain_duration` and `exact_rc_artifact` fail for each. PASS (audit exit 0; the evidence itself FAILS promotion). Full machine-readable output: job directory `writer-evidence-audit.json`.
- Auth investigation — first command failed import as recorded above; corrected `PYTHONPATH=packages/maistro-server/src uv run python` verified both credential forms against the production resolver (PASS). This disproved the suspicion and avoided a speculative edit.

## Acceptance matrix at this head

| #860 criterion | Executed evidence / disposition |
| --- | --- |
| Representative concurrent users/Workspaces, request mix, Graph fan-out, schedules, model/tool/Design/Canvas/background work | **PARTIAL / UNVERIFIED**. Inspected profile and actual `main_async` mix: one key, health/tasks/metrics; profile lines 152–166 explicitly identify missing surfaces. No representative RC population was run. |
| At least two application replicas | **UNVERIFIED for RC**. Production Compose names two application services; production boot-contract tests pass configuration assertions. Those tests do not start the replicas; historical host processes are not the exact production topology. |
| Sustained saturation, queue growth, lease reclaim, retry, leaks and restart | **UNVERIFIED**. Current evaluator rejects all four historical packs; round 5/6 observed 90.17/90.43 seconds, not 14400. Live process-group regression passed but is not sustained application telemetry. |
| No duplicate physical schedule/task/Run/Attempt work, Goal reconciliation | **UNVERIFIED**. Admission-oracle tests pass; `phase_claim_probe` races an occurrence and cancels its queued Run without executing it. It cannot establish physical-work uniqueness or Goal reconciliation under load. Accepted fencing/reclaim ADRs remain authoritative. |
| Rate limiting, security and degraded behavior cannot be bypassed by replica selection | **NOT MET**. Executed both cases of `test_replica_selection_has_an_independent_production_allowance`: same identity sees `[200, 200, 429]` on each limiter instance. `rate_limit.py:25–30` documents independent per-process allowance. Six-path probe tests establish local enforcement only. RC security/degraded concurrency proof remains UNVERIFIED. |
| Complete telemetry with explicit pass/fail thresholds | **PARTIAL / UNVERIFIED**. Profile defines H1–H6/S1–S5; sampler and gate regressions pass. Application-loop latency is not driver lag; complete RC worker/process/connection/lock/queue/leak/error measurements were not captured. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Historical exit/rejoin counts are not physical Attempt correlation, and no current exact-RC active-work failure injection ran. |
| Long-running soak of exact RC artifact/config; rerun after changes | **NOT MET**. `preflight_artifact_check` always returns false; executed CLI regressions reject even synthetic four-hour preflight results. No immutable RC image/config selection was supplied and no promotion-capable runner exists in the inspected driver. Do not spend four hours on a runner that cannot meet this criterion. |
| Findings filed/reclassified to earliest milestone | **PARTIAL / UNVERIFIED**. Existing human pack records load findings and M3-A evidence-validity classification (F11/F12). No new load findings were generated; no external filing was verified or performed (GitHub mutations prohibited). |
| Machine/human soak evidence tied to exact image/package/commit/config hashes | **PARTIAL / UNVERIFIED**. Existing packs and hash collector were inspected and machine-evaluated; they identify historical preflight, not the promoted RC Compose image/config. This report and job audit are validation evidence, not soak evidence. |

## Final handoff

**BLOCKED.** The requested exact-debt gate is green at the assigned head, but #860's release acceptance is not complete. No source, runtime configuration, historical evidence, inventory count, or ledger identity was changed. No tests were added, so no inventory delta is necessary. The only changed file is this report, committed locally as the required checkpoint.

Next owner needs to select immutable RC image/config identities, resolve the replica-selection allowance mismatch without creating another authorization path, implement the missing production-topology workloads/measurements, then run at least 14400 seconds with active-work failure injection and physical Attempt/fence correlation. Any code/config change requires a new qualifying soak. Rerunning this host preflight longer is not a resolution.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC soak and non-bypass blockers"}`. All ten acceptance criteria were assessed above; none is silently waived. The transient import failure is documented and resolved, not counted as an outstanding validation error.
