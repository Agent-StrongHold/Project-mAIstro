# Issue #860 — job 5b37f232 repair checkpoint

## Frozen scope

- Assigned issue: #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `7f651a73eaa8cfa32ad6c9328eb237e8abc601b9`; working tree initially clean.
- Supplied comparison base: `45cc963267a157a9530ea4f0f688f27fdb83f3ae` (resolved by initial diff).
- Process existing load profile/evidence, soak harness and promotion tests, adjacent PostgreSQL-learning and task-backpressure tests, production rate limiter/deployment contract, relevant ADRs, and exact vulture gate only.
- Candidate edits: this handoff; evidence/profile corrections only if contradicted by current production behavior; vulture source/ledger changes only if the exact scan reports actual findings. No new runtime feature or alternate execution authority.
- No remote mutations, ref changes, or disposal of existing work.

## Initial results / ambiguities

- Job directory snapshot contains `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`; no `check-*.log` files exist to inspect. Driver verification therefore cannot be assumed.
- Previous result artifact exists at the supplied path and will be read once.
- This branch already contains extensive historical repair notes; they will not be re-enumerated. Current acceptance must be checked against production and executable tests, not repeated historical claims.
- The supplied base diff includes unrelated historical changes. This round preserves them without expanding scope.

## Validation

- Exact requested vulture command passed: 1,343 findings = 1,343 reviewed identities, unclassified=0, never_allowlist=0; trusted base resolved to `c0441cf94b9a`. No unbanked identity exists to repair or amend; ledger unchanged.
- Prior result read: BLOCKED; it is not accepted as current validation.
- Current evidence pack already corrects the historical H3 claim: process-local enforcement is not replica-selection non-bypass. No speculative documentation repair is needed.
- ADR reconciliation: accepted ADR-081426-1f7c makes Attempt the physical execution identity; accepted ADR-081626-f383 explicitly does not define lease-expiry takeover. Admission-only races cannot prove physical fencing/reclaim. ADR-085 requires per-principal limiting but supplies no cluster-wide HTTP limiter. ADR-081 remains Proposed, not an accepted override of the issue's deployment evidence requirement.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped** in 2.88 s. Skips explicitly require `MAISTRO_TEST_PG_DSN` to a migrated PostgreSQL database (lines 766, 877, 896, 906, 917 in the learning tests). No live database validation is claimed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2,850 files).
- `uv run python scripts/check-ratchet-provenance.py`: passed; trusted base `c0441cf94b9a`; 46 consumers have explicit provenance. Existing SyntaxWarning about an invalid escape sequence and development CORS warnings did not fail the gate.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- Executed an inline `uv run python` check importing the current soak module, loading the fixed historical `m3a-round6-shakedown.json` path and invoking `failed_promotion_checks`. Result: `sustain_seconds=90.43`, minimum `14400`, failures exactly `sustain_duration` and `exact_rc_artifact`; assertions confirming rejection passed. `preflight_artifact_check()` returns `ok=false`, topology `host-uvicorn-preflight`. This evaluates historical evidence, not a new soak.

## Acceptance review (all ten criteria)

| Criterion | Current evidence and remaining acceptance gap |
|---|---|
| Representative RC load profile | **PARTIAL / UNVERIFIED**. `m3a-load-profile.md` defines request mix, phases and thresholds, but its remaining-profile-gaps section explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool work, Design/Canvas and Goal/background-worker traffic. Production Compose requires a reachable model gateway; the preflight intentionally has none. No complete RC profile is established. |
| At least two application replicas | **Historical preflight only / RC UNVERIFIED**. `deploy/docker-compose.prod.yml:22-23,78-79` names two services. Run-6 evidence records two host processes, not those exact application images/configuration. No new two-replica deployment was exercised in this round. |
| Sustained saturation, reclaim, retry and leak observation | **UNVERIFIED**. `evidence/m3a-round6-shakedown.json:165,221-224` records 90.43 s against 14,400 s. The executed current evaluator rejects it. Wrapper-only historical RSS/FD measurements are expressly invalidated by the evidence pack. Passing live-child sampler regression is not a long application soak. |
| No duplicate physical work, admission and Goal reconciliation | **UNVERIFIED**. H1 probe regression cases reject empty/all-conflict receipts and mixed identities; backpressure test reaches the real task router, queue and in-memory canonical Run store. These do not execute physical Attempts across replicas. The schedule probe cancels its one queued Run and cannot establish physical fencing or sustained Goal reconciliation. Accepted lease ADR does not grant implicit reclaim authority. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | **NOT MET**. `rate_limit.py:25-30` specifies independent replica budgets; production installs this middleware at `main.py:593`. Executed `test_replica_selection_has_an_independent_production_allowance` proves identical credentials/IP receive `[200,200,429]` on each instance. Six-path probe tests detect a disabled replica, but do not create a shared budget. Backpressure behavior is tested (429 with Retry-After, per-principal isolation, readmission after slot release); broader RC security/degraded behavior remains unverified. |
| Full telemetry and explicit thresholds | **PARTIAL / UNVERIFIED**. `run_soak.py:455-489` samples process groups, dedicated SQL round-trip, connection and waiting-lock counts, and Run status depth. Regression tests prove child growth and incomplete-measurement handling. Driver event-loop lag is not application event-loop lag; detached workers, application query latency, saturation and complete pass/fail leak/timeout thresholds remain unproven under an RC run. |
| Active-work kill/restart and graceful fencing/recovery | **UNVERIFIED**. Historical run-6 process exit/rejoin and zero nonterminal Runs do not correlate in-flight physical Attempt side effects. No active-work fault injection was executed this round. |
| Long soak of exact RC artifact/configuration | **NOT MET**. `run_soak.py:635-646` unconditionally rejects host-preflight artifact equivalence; executed CLI regression cases reject even synthetic four-hour preflight evidence. The assignment supplies source refs, not a selected immutable RC image/configuration manifest; no such manifest/run was produced here. A four-hour emulator run would not resolve the blocker. |
| Findings filed/reclassified to earliest milestone | **PARTIAL / external filing UNVERIFIED**. Evidence pack locally classifies F11/F12 as M3-A evidence-validity defects and records runtime findings. No GitHub mutation is permitted or performed. Release owner must confirm filing and disposition before promotion. |
| Hash-bound machine/human evidence | **Historical preflight only / RC UNVERIFIED**. JSON/logs and human pack exist for historical heads. They do not prove the current production artifact/configuration; this validation note is not a substitute for promotion evidence. |

## Disposition and next action

**BLOCKED**, not integration approval. CI-repair inspection found no unbanked vulture identity; changing a ledger or runtime simply to create a repair diff would be unsupported. The H3 documentation contradiction named in the prompt is already corrected in the current tree. Existing source, historical evidence and ledgers are preserved unchanged.

Only this handoff document is changed. No tests were added or removed, so no inventory delta is required. The earlier 57-test claim is superseded by this round's executed 80-pass/5-skip result for these exact paths; no full-tree pytest claim is made.

Next: release/deployment owner must select the exact immutable RC image/config manifest, resolve the documented per-process-rate-limit/non-bypass mismatch and missing workload/telemetry surfaces, then execute and publish an instrumented >=14,400 s production-topology run with physical Attempt side-effect accounting and active-work restart/fencing observations. Do not repeat a short host-preflight run or a ledger-only repair as a substitute. Any runtime/config repair requires a new soak.

Progress: checked=1 assigned issue, done=0 acceptance-complete issues, skipped=0 issues, errors=0 validation-command failures; acceptance remains blocked. Local documentation checkpoint will be committed; no push or remote mutation.
