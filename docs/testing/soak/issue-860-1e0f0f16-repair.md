# Issue #860 repair checkpoint — job 1e0f0f16

## Frozen scope

Only issue #860; starting head `c038eb602bd483115fb1623bf714564e81f7a204`, supplied base `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Worktree was clean. No other issues or linked PRs will be processed.

Review surfaces: repository instructions, relevant execution/release ADRs, `scripts/soak/`, `tests/test_soak_promotion_gates.py`, associated production admission/rate-limit/receipt paths, the cited prior check log, and the vulture checker/workflow. Permitted edits are this report and `quality/vulture-baseline.json` only if the exact scan demonstrates reviewed retained identities needing amendment. No speculative runtime repairs or gate changes.

The supplied job directory contained no `check-*.log` files at initial inspection. The prior result reports BLOCKED; that is a claim to validate, not acceptance evidence. Ambiguity: no designated exact RC artifact/configuration was supplied. Proceed with focused local regression and gate validation, not a substitute production soak.

## Executed checkpoint

- Exact prescribed vulture scan passed (exit 0): 1,322 findings / 1,322 reviewed identities; zero unclassified or forbidden identities. No ledger amendment is justified.
- The cited prior `check-3.log` fails `test_ensure_schema_fences_ddl_behind_advisory_lock`: 24 actual DDL statements versus 21 expected. Revalidate that specific existing test before assuming a repair is still needed.
- Accepted release ADR-073126-c4e1 requires an immutable RC and promotion of the validated artifacts; a local shakedown cannot satisfy that contract.

## Focused validation results

All commands ran in the assigned worktree, with 600–1,200 second tool timeouts:

| Command | Result |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1,322 reviewed identities match 1,322 findings. Same scan arguments as `.github/workflows/vulture-ratchet.yml:82`. |
| `uv run ruff check .` | Exit 0, all checks passed. |
| `uv run ruff format --check .` | Exit 0, 3,301 files already formatted. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q` | Exit 0, 109 passed, 6 skipped. Skips are not acceptance evidence. |
| `uv run python scripts/check-backlog-consistency.py` | Exit 0, 168 items consistent. |
| `uv run python scripts/check-suite-inventory.py` | Exit 0, all 17 suites match; 31,323 unique collected identities. Collection is not execution. |

The prior schema failure is not reproducible at the assigned head: the existing test independently lists the three validation audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175`, and passes against the production schema upgrade. No new test or runtime edit is justified by that historical log. No tests added or removed; no inventory note needed.

## Acceptance assessment

| #860 criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md` explicitly lists missing users/Workspaces, Graph fan-out, successful calls, Design/Canvas and background workloads. No designated RC configuration supplied. |
| At least two deployed replicas | **UNVERIFIED.** Executed tests use ASGI instances, not deployed production replicas. |
| Sustained saturation, reclaim, retry, leaks | **UNVERIFIED.** No sustained production load executed this round. |
| Physical-work uniqueness across admission/reconciliation | **UNVERIFIED.** Passing admission/probe tests do not establish absence of duplicate physical work. |
| Security cannot be bypassed by replica selection | **NOT PROVEN.** `tests/test_soak_promotion_gates.py:439` executes real `RateLimitMiddleware` twice with one identity; each replica accepts two requests then returns 429. Independent allowances remain observable. |
| Production telemetry with thresholds | **UNVERIFIED.** Profile thresholds exist; no new production telemetry captured. Driver loop lag is not application loop lag. |
| Kill/restart active work, drain/fencing/recovery | **UNVERIFIED.** No production restart executed. Process rejoin alone is not physical-work recovery. |
| Long exact-RC soak, rerun after changes | **UNVERIFIED / BLOCKED.** `scripts/soak/run_soak.py:744` returns `ok=False` for exact-artifact equivalence, and the tested promotion evaluator requires that check. No designated immutable RC image/config supplied. |
| Classify findings to earliest broken invariant | **UNVERIFIED for completeness.** Backlog consistency passed; no new load run or GitHub mutation performed. Existing findings are not waived. |
| Machine/human evidence bound to artifact hashes | **UNVERIFIED for promotion.** This report records local validation only, not an image/config-bound production soak. |

Additional observed regression: `tests/test_soak_promotion_gates.py:564` passes through the production task router, reads an admitted receipt locally (200), then observes 404 from the peer queue. The router is installed by `packages/maistro-server/src/maistro_server/main.py:735,755`; rate limiting is installed at line 648. These are reachable production components, but ASGI probes are not a deployed soak.

## Architecture and handoff

Read repository `AGENTS.md`, documentation authority map, accepted release ADR-073126-c4e1 and occurrence-claim ADR-082426-82c7. Reconciliation: occurrence admission uniqueness is not proof of physical execution uniqueness; the canonical Run store remains the claim authority. No competing scheduler, execution store, event authority or authorization path introduced. An immutable release candidate's validated artifacts must be promoted; extending the host-process preflight duration cannot satisfy that decision.

Only this report changed. The CI-repair request has no remaining demonstrated vulture or schema-test defect at the assigned head. Residual blockers require a designated exact RC artifact/configuration and representative deployed workloads, including resolution or explicit contract reconciliation of observed replica-local behavior. Do not run repeated cosmetic repair rounds or amend a matching ledger as a substitute.

Progress: checked 1 issue; completed focused gate validation; issue acceptance blocked; skipped 0 issues; failed validation commands 0. Next: release owner supplies the exact RC and deployment configuration, then production-path soak and invariant repairs can be evaluated. Verdict: **BLOCKED**, not integration approval.
