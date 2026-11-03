# Issue #860 — repair validation f4b3d3ab

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head `0235d91a313b329d8f599b18b8278a804c11b865`; supplied base
  `eec7a587039e632500942dd390f82d743863f5e3`.
- One item: issue #860, including the explicitly assigned vulture CI repair.
  No linked PR or other issue will be processed.
- Initial worktree clean; no incoming edits to salvage.
- Input: supplied dispatch snapshot and prior result `0af1d125`; these are
  historical claims, not executed validation for this round.
- Job directory contains no `check-*.log` files; driver logs not found; skipped.
- Inspection scope: repository instructions, relevant execution/release ADRs,
  `scripts/soak/run_soak.py`, adjacent soak tests, server rate-limit wiring,
  load profile, round30 evidence, CI gate configuration and prior repair report.
- Planned write scope: this report only unless a reproduced gate failure
  identifies a concrete repair. No speculative ledger or authorization changes.

## Ambiguity and assumption

The assignment requests a repair and an exact-RC soak, but supplies no selected
RC artifact/configuration. Treat existing shakedowns as non-promotion evidence;
do not relabel them or choose an arbitrary artifact as the release candidate.
Follow accepted ADRs rather than inventing a shared admission/security authority.

## Executed validation

- Exact requested vulture command: PASS, 1322 findings / 1322 reviewed
  identities, zero unclassified or never-allowlist findings. CI arguments
  confirmed in `.github/workflows/vulture-ratchet.yml:82-85`. No ledger
  amendment is supported by this evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3306 files already formatted.

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS, 84 tests.
  This executes both authenticated and unauthenticated replica-selection
  counterexamples using the production middleware.
- `uv run python scripts/check-suite-inventory.py`: PASS, all 17 suites,
  31,489 unique test identities; `tests/` collects 5354. The reported
  5353/5354 mismatch does not reproduce. No inventory change warranted.

The profile explicitly describes the current runner as a host-process preflight,
not the selected production RC artifact. Passing evaluator tests do not establish
production soak acceptance.

- `uv run pytest packages/maistro-server/tests -x -q`: PASS, 566 passed,
  8 skipped, 22 HTTP-status deprecation warnings (33.36 seconds).
- `uv run python` imported the current soak evaluator and evaluated
  `evidence/m3a-round30-shakedown.json`: asserted failures are exactly
  `sustain_duration` and `exact_rc_artifact`. Observed 420.08 seconds versus
  14,400 required, historical head `c4f45b309fd622f2e8a4b315dad35e721d81aad3`.
  Also asserted current `preflight_artifact_check()['ok'] is False`.
- `git diff --check`: PASS.

## Architecture and reachable behavior

Read accepted ADR-085, ADR-081626-f383, ADR-082426-82c7 and
ADR-082526-b36a. The later lease-reclaim ADR fills the earlier fencing ADR's
explicitly deferred expiry boundary. Preserve `Goal -> Graph -> Run -> NodeRun
-> Attempt`; admission uniqueness is not physical execution fencing. Occurrence
claims belong on canonical Runs, and renewal/reclaim authority remains with
canonical Attempts, their store and execution lifecycle. No competing scheduler,
store, authorization or execution authority was introduced.

ADR-081, cited by the load profile, is **Proposed**, not an accepted waiver.
ADR-085 mandates per-principal rate limits but does not waive #860's
replica-selection criterion. The production app installs `RateLimitMiddleware`
at `packages/maistro-server/src/maistro_server/main.py:648`; each middleware
instance constructs its own in-memory limiter (`api/rate_limit.py:93-100`).
The executed tests at `tests/test_soak_promotion_gates.py:477-526` send the same
identity to two instances: each returns `[200, 200, 429]`. Thus local enforcement
works, but switching replicas grants another allowance. This is not proof of a
replica-independent budget, as the production module itself states at lines
32-37. No speculative security-policy change was made as a vulture repair.

## Acceptance matrix (supplied issue body)

| Criterion | Evidence / disposition |
| --- | --- |
| At least two application replicas | **UNVERIFIED for selected RC**. Executed two-instance middleware tests are not a deployed production topology soak. |
| Sustained saturation, queue growth, reclaim, retry, leaks and restart observations | **UNVERIFIED**. Evaluated historical evidence is only 420.08 seconds; profile lines 167-183 explicitly retain saturation, reclaim and long-window gaps. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED**. Historical occurrence evidence cancels its probe Run (`m3a-round30-shakedown.json:11-15`); admission uniqueness does not establish physical-work fencing or Goal reconciliation. |
| Rate/security/degraded enforcement resists replica selection | **NOT PROVEN**. Executed real-middleware tests reproduce independent budgets for authenticated and unauthenticated identities. Sustained security/degraded observations remain unverified. |
| Complete production telemetry and explicit thresholds | **UNVERIFIED**. Profile has partial thresholds, but driver-loop lag is not application-loop lag; worker/pool/lease and long-window observations remain missing (profile lines 167-183). No fresh RC telemetry captured. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Historical process exit/rejoin and terminal Run counts do not establish physical-work fencing/recovery; no new active-work exercise performed. |
| Long-running exact RC artifact/configuration | **NOT MET by evaluated evidence**. Both duration and artifact gates fail. No selected immutable RC image/configuration supplied; the current runner explicitly cannot certify one (`run_soak.py:744-755`). |
| Findings filed/reclassified at earliest broken invariant | Local report preserves the security-budget and execution-proof blockers; **external filing/reclassification UNVERIFIED**. GitHub mutations prohibited and not performed. |
| Machine/human evidence tied to exact promoted hashes | **UNVERIFIED for current RC**. Historical machine evidence names an older host-process preflight; no new promotion-grade run or identity evidence was produced. |

Representative coverage is additionally incomplete: profile lines 167-183 and
215-217 exclude successful model/tool/Canvas, Graph fan-out, sustained Goal
reconciliation and physical Attempt fencing. More elapsed time in the unchanged
preflight does not repair those missing workloads or artifact identity.

## Outcome and handoff

**BLOCKED**: the previous acceptance block remains unresolved. This is not a
merge conflict; no develop merge was necessary. The specifically assigned CI
failure did not reproduce, so ledger amendments or test-count changes would be
unsupported. No live soak was attempted and no promotion claim is made.

Changed file: this report only. No code, tests, historical evidence, inventories,
quality ledgers or grants changed. Existing meaningful tests ran afresh; no test
addition requires an inventory-delta note. All validation commands passed;
rejection of historical evidence is the expected evaluator result, not a passing
soak.

Next required input/work: select the immutable RC artifact/configuration and its
supported workloads; resolve the replica-independent budget requirement through
the existing canonical authentication/limiter path; execute an instrumented
production-path >=4-hour soak with active physical-work recovery, lease reclaim,
Goal reconciliation and complete application telemetry. Do not re-dispatch an
unchanged vulture-only repair expecting it to supply this evidence.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands, blocked 1. This checkpoint is committed locally;
no push or other GitHub mutation.

