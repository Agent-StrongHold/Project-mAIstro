# Issue #860 — b2502773 repair checkpoint

## Frozen assignment and scope

- Writer: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `54a226973b58446b44e9d988c1fb8039535ccfe2`; initial working tree clean.
- Supplied base `45cc963267a157a9530ea4f0f688f27fdb83f3ae` resolved by initial diff.
- Single item: issue #860 and its explicit vulture CI-repair request. Inspect existing soak profile/evidence, harness/promotion tests, adjacent learning/backpressure tests, production limiter/deployment, and relevant ADRs. Do not expand to unrelated historical base differences.
- Candidate changes: this checkpoint; corrections only for demonstrated defects in the above scope; vulture ledger/source only for actual scan findings. Preserve all existing work.
- Job directory snapshot: `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`; no `check-*.log` files supplied. Driver checks are unavailable, not assumed green.
- Previous result and its checkpoint were read, but their validation claims are not reused as this round's results.

## Executed results

- Exact assigned vulture command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` **passed**, 1,343 findings / 1,343 reviewed identities, zero unclassified or never-allowlist identities; trusted base `c0441cf94b9a`. No evidence supports a ledger amendment or dead-code deletion.
- Current load profile explicitly says the host-uvicorn preflight cannot sign promotion evidence, requires >=14,400 seconds on the exact RC artifact, and documents missing representative workload surfaces. This is an acceptance blocker, not a reason to repeat a short emulator run.

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped** (2.78 s). The five live-PostgreSQL tests require `MAISTRO_TEST_PG_DSN`; no live DB claim is made. Executed tests include real production-middleware independent replica allowances, six-path rate-probe failure cases, invalid admission receipts, CLI artifact rejection and a real uv-child resource sampler.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed (2,850 files).
- `uv run python scripts/check-ratchet-provenance.py`: passed (46 consumers, trusted base `c0441cf94b9a`). Non-fatal existing SyntaxWarning and development CORS warnings appeared.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- Inspected current evidence pack: the prior H3 shared-store assertion is already corrected at `m3a-soak-evidence.md:171`; it explicitly distinguishes local enforcement from replica-selection non-bypass. No new cosmetic repair is warranted.

## ADR reconciliation

Accepted ADR-081426-1f7c identifies physical execution by Attempt, not Run. Accepted ADR-081626-f383 protects persisted transitions with canonical-store fences and explicitly does not define lease-expiry takeover. A schedule admission race cannot establish physical-work uniqueness or imply a new reclaim authority. Accepted ADR-085 requires per-principal limits but does not prescribe a cluster-wide HTTP limiter. ADR-081 is Proposed, not an accepted waiver for missing production-topology evidence. No execution or authorization authority is changed in this round.

## Acceptance review

Executed an inline `uv run python` check importing the current harness and evaluating the fixed historical path `docs/testing/soak/evidence/m3a-round6-shakedown.json`. Assertions passed: actual recorded duration 90.43 seconds is below 14,400; `failed_promotion_checks` returns `sustain_duration` and `exact_rc_artifact`; `preflight_artifact_check()` returns `ok=false`. This is evaluation of old evidence, not a new soak.

| Acceptance criterion | Evidence / disposition |
|---|---|
| Representative release-candidate profile | **PARTIAL / UNVERIFIED**: `m3a-load-profile.md` defines a mix and thresholds but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and Goal/background-worker workloads. No selected RC configuration justifies these omissions. |
| At least two application replicas | **RC UNVERIFIED**: `deploy/docker-compose.prod.yml:22-23,78-79` declares two servers; historical host-process evidence is not an execution of that image/configuration. No replicas were launched this round. |
| Sustained saturation, growth, reclaim, retries and leaks | **UNVERIFIED**: historical 90.43 s window is rejected by the current evaluator. A passing child-process sampler test is not a long application soak. Lease takeover cannot be invented contrary to the accepted fencing boundary. |
| No duplicate physical work, admissions and Goal reconciliation | **UNVERIFIED**: admission-oracle regressions reject empty/conflicting receipts; the existing schedule probe races admission but cancels its queued Run without physical execution. No cross-replica Attempt side-effect accounting or sustained Goal reconciliation was executed. |
| Rate/security/degraded behavior, no replica-selection bypass | **NOT MET**: production installs the limiter at `main.py:593`; `rate_limit.py:25-30` specifies independent budgets. Executed `test_replica_selection_has_an_independent_production_allowance` confirms the same authenticated or unauthenticated identity receives `[200,200,429]` on each instance. Backpressure regression proves router-level 429/Retry-After, principal isolation and readmission after slot release, not global rate-budget enforcement. |
| Complete telemetry and explicit thresholds | **PARTIAL / UNVERIFIED**: `run_soak.py:455-489` samples process groups, dedicated SQL probe latency, connection/lock counts and Run depth. Tests exercise child growth and missing observations. These do not establish application-loop latency, application-query latency, detached worker counts or complete long-window pass/fail leak/timeout thresholds. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**: historical process rejoin/terminal Run counts are not correlated physical Attempt effects. No active-work kill/restart was executed in this round. |
| Long exact-RC artifact/configuration soak | **NOT MET**: `run_soak.py:635-646` rejects host-preflight equivalence; executed CLI regressions reject even synthetic four-hour preflight evidence. Assignment supplies source refs, not an immutable RC image/config manifest. No >=14,400 s exact-RC run was produced. |
| Findings filed/reclassified to earliest invariant | **PARTIAL / external filing UNVERIFIED**: human pack locally classifies F11/F12 as M3-A evidence-validity failures. No remote filing was performed or independently verified; GitHub mutations are prohibited. |
| Hash-bound machine/human evidence | **Historical preflight only / RC UNVERIFIED**: historical JSON/logs and human interpretation exist, but do not sign the current promoted image/configuration. This checkpoint is not promotion evidence. |

## Disposition

**BLOCKED.** The specifically assigned vulture gate has no outstanding finding. The reported H3 prose contradiction is already repaired. Neither a speculative ledger amendment nor another short preflight run would address the remaining release evidence gap.

Changed file: this checkpoint only. No tests added/removed, so no inventory delta is required. Runtime, ledgers and historical evidence remain unchanged. Validation does not approve integration or issue closure.

Next: release owner must select an immutable RC image/config manifest, resolve the non-bypass contract mismatch and representative-workload/telemetry gaps, then execute an instrumented >=14,400 s production-topology run with physical Attempt side-effect accounting and active-work restart/recovery evidence. Any runtime/config repair requires a new soak. Repeating ledger-only repair rounds cannot satisfy these acceptance criteria.

Progress: checked=1, done=0 acceptance-complete issues, skipped=0 issues, errors=0 validation-command failures; next=release-owner RC/config selection and acceptance-blocker resolution. This checkpoint is committed locally; no push or remote mutation.
