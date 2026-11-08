# Issue #860 — bounded CI-repair handoff

## Scope and decision

Writer job `f870aae904ff4c18b951f852c2e50957`, worktree
`/home/dev/Git/wt/auto-860`, branch `auto-860`; clean starting head
`d5f192abc3b94475a8ed96fb452dacf1db4ea592`, dispatch base
`ce2048cd2430bf99a5896b229fd1999976dc07dd`. Only issue #860 processed.
No driver `check-*.log` files existed in the supplied job directory. Fresh
validation logs are recorded there as `worker-*.log`. The full acceptance
body was read from the frozen dispatch context (the first source contained
only its trailing four criteria). No remote enumeration or mutations.

The exact requested Vulture command passes: **1322 reviewed identities / 1322
findings**, no unclassified or never-allowlist identities. Therefore there is
no evidence-based ledger amendment or dead-code removal to perform. The
explicit CI-repair exception permits reviewed amendments, not invented debt.
No quality ledger, runtime, configuration, test, or historical evidence changed.

Root inventory drift is reproduced: expected **5353**, collected **5354**.
Bounded provenance inspection found three changed root test files relative to
scanner-selected merge base `2f56be40ad241262b0384ab0b97834ebd37fe4d7`:
`test_soak_promotion_gates.py`, `test_prod_stack_boot_contract.py`, and
`test_gitleaksignore_contract.py`. Current focused collection yields 84, 8,
and 8 cases respectively. Added inventory notes record net +93 root cases,
including the +1/-1 wheel-verifier overlap correction. This does not identify
an omitted case; provenance remains **UNRESOLVED**. No guessed +1 delta,
shared baseline change, or test deletion is justified. No tests were added in
this round, so no inventory-delta note is needed.

## Architectural reconciliation

Read repository instructions and accepted ADR-081226-a66b (one logical
Run/NodeRun/Attempt lifecycle), ADR-085 (per-principal rate limiting),
ADR-082526-b36a (lease renewal/reclamation), ADR-082826-08f0 (recovery by proven
liveness), and ADR-082526-547c (inventory deltas). Recovery must use existing
canonical leases and reconciliation, not a second scheduler or authority.
Local middleware budgets do not establish the issue's stronger
replica-selection-resistant allowance. The profile's admitted gaps are
blockers, not waivers of the issue's acceptance criteria.

## Validation

All commands ran in the assigned worktree with 1000-second timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322/1322 identities |
| `uv run python scripts/check-suite-inventory.py --suite tests` | FAIL, expected 5353, collected 5354; no byte-identical files |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py --collect-only -q` | PASS, 100 cases |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3306 files |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | PASS, 127 tests |
| `uv run python scripts/check-deployment-claims.py` | PASS; declared component existence only |
| `uv run python` importing current `scripts/soak/run_soak.py` and evaluating round30 JSON with `failed_promotion_checks` | Rejects `sustain_duration` and `exact_rc_artifact`: 420.08 seconds vs 14400 minimum, host-uvicorn-preflight |

The 127 executed tests include both authentication variants of
`test_replica_selection_has_an_independent_production_allowance`
(`tests/test_soak_promotion_gates.py:481-529`). They instantiate the production
middleware twice for the same IP/credential; each independently accepts two
requests then returns 429. This demonstrates the allowance increase, not a
passing cluster-wide-budget claim. Production creates each in-memory limiter
in `packages/maistro-server/src/maistro_server/api/rate_limit.py:92-100`,
consistent with its documented N×limit scope at lines 32-37.

## Acceptance evidence

1. **Representative profile: UNVERIFIED.** A profile exists, but
   `m3a-load-profile.md:167-183` explicitly excludes concurrent
   users/Workspaces, Graph fan-out, successful tool/model/Canvas work and
   sustained Goal reconciliation. No fresh production workload ran.
2. **Two supported production replicas: UNVERIFIED.** Boot-contract tests
   passed, not a live exact-RC deployment test.
3. **Sustained saturation, reclaim, retry and leak observation: UNVERIFIED.**
   Fresh evaluator execution rejects the supplied 420.08-second evidence.
4. **Exactly-once/fenced physical work and Goal reconciliation: UNVERIFIED.**
   Profile lines 215-217 state the schedule probe cancels its queued Run
   without execution. Admission counts cannot prove physical-work safety.
5. **Replica-selection-resistant rate/security/degraded behavior: NOT MET
   in the tested middleware path.** Executed tests reproduce two independent
   allowances for one identity. Narrow security/backpressure tests pass;
   they do not prove the stronger aggregate requirement.
6. **Required production metrics and thresholds: UNVERIFIED.** Thresholds
   are documented, but profile lines 179-183 distinguish driver loop lag
   from application latency and leave pool/worker/reclaim observations open.
7. **Active-work kill/restart with drain/fencing/recovery: UNVERIFIED.** No
   fresh production kill/restart ran. Process rejoin and terminal Run counts
   do not establish physical-work safety.
8. **Long-running exact RC: NOT MET by supplied evidence.** Current evaluator
   rejects both duration and artifact identity. A longer host-process run
   cannot prove the promoted Compose artifact. No selected immutable RC and
   normalized production configuration were supplied for this repair.
9. **Findings filed/reclassified: UNVERIFIED.** Findings recorded locally;
   remote mutations prohibited. No external filing or closure claimed.
10. **Machine/human evidence bound to promoted hashes: UNVERIFIED.** Round30
    names an older preflight head/configuration; no fresh promotion artifact
    evidence produced or historical evidence rewritten.

## Handoff

**BLOCKED.** Only this report changed. Required scanner repair is unnecessary
on the observed tree; inventory provenance and promotion evidence remain
unresolved. Existing production behavior and all inherited work are preserved.
Do not promote or restart another identical short-preflight repair cycle.
Next work needs an identified immutable RC/configuration, a representative
production workload with physical-work/recovery instrumentation, resolution of
the aggregate-rate acceptance gap, and a fresh ≥4-hour exact-artifact soak.
The +1 inventory discrepancy needs a separately attributable node/delta before
any accounting amendment. No replacement execution or authorization authority
is warranted.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: inventory provenance and production RC soak prerequisites}`.
