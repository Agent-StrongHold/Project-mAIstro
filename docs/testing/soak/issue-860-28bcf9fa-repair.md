# Issue #860 — repair validation (job 28bcf9fa)

## Frozen scope and initial state

- Assignment: issue #860 only, including its explicit vulture exact-debt-ledger gate.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `c789344f1bab6b943d869333b819f2045def496e`.
- Assigned base: `b35cdcbd1946af616a0cced308202edd72588a9b`.
- Initial working tree clean; no incoming changes to salvage.
- Prior result `db8066a33f194c099aab7e77be9ada30/result.json` read; its
  BLOCKED verdict is context, not fresh validation.
- Initial job directory listing contains no `check-*.log` files. Driver check
  evidence is unavailable in this snapshot; run focused validation locally.

## Frozen processing list

One item: #860. Inspect the existing soak harness, profile, evidence summary,
its four historical JSON evidence packs and adjacent promotion-gate tests;
the rate limiter and backpressure/schema-fence regression tests; relevant
accepted ADRs and production deployment contracts. Execute the prescribed
vulture gate and focused validation. Modify the vulture ledger or production
code only for an actual reproduced defect within this assignment. This report
is the only planned new file; new tests, if needed, require an inventory note.
No other issue/PR enumeration or GitHub mutation is authorized.

## Ambiguity and assumption

The brief calls this a repair but supplies no promotable RC image/configuration
or external four-hour execution evidence. Assume the existing host-process
harness remains a preflight, not equivalent to a production Compose artifact.
Do not relabel short runs as acceptance, invent artifact identity, or change
rate-limit architecture as a side effect of an evidence repair. Verify those
boundaries against source and tests before deciding the final status.

## Results

- Prescribed vulture exact-debt command PASS: 1373 reviewed identities match
  1373 findings; no unclassified/never-allowlist identities. The tool resolves
  trusted baseline `a74a2b939a1e`; candidate is the assigned starting HEAD.
  No actual ledger drift remains, so do not amend a passing ledger.
- Current evidence summary already retracts the old shared-limiter claim.
  Production middleware constructs an `InMemoryRateLimiter` per instance;
  its documented N-times allowance is not #860 non-bypass proof.
- Production Compose declares two app services but is explicitly a reference
  artifact with unpinned builds and required external model gateway settings.
  The load profile explicitly excludes exact-artifact promotion for its
  host-process runner and lists unresolved representative-workload gaps.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS
  (2712 files already formatted).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  -x -q -rs`: **88 passed, 5 skipped in 103.44s**. The five PostgreSQL tests
  skip without `MAISTRO_TEST_PG_DSN`; no live DB/concurrent-DDL proof claimed.
  Existing tests exercise the real task router and canonical in-memory spine,
  real per-instance rate middleware, live child-process resource sampling,
  preflight artifact rejection and production config startup contracts.
- `uv run python scripts/check-compose-secrets.py`: PASS (8 Compose files).
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS
  (4320 cases). No tests added/changed; no inventory delta required.
- Commands used 1200-second timeouts. Logs: `worker-pytest.log`,
  `worker-ruff.log`, `worker-format.log`, `worker-compose.log`,
  `worker-inventory.log` in the assigned job directory. Vulture result is in
  the tool transcript; it passed without changes.
- Accepted ADR-081426-1f7c makes physical execution identity the Attempt ID;
  ADR-081626-f383 assigns lease/fence authority to the canonical Run store;
  ADR-082126-f69c prohibits a second schedule runtime. Admission counts or
  process rejoin cannot substitute for physical-work fencing/recovery proof.
  ADR-085 requires per-principal rate policy; independent counters cannot be
  described as shared. Deployment ADR-081 is Proposed, not a waiver of #860.
  No architecture changes or competing authority introduced.
- Artifact check first failed with `KeyError: 'sustain_seconds'` in the
  one-off validation command (`worker-evidence.log`): older packs lack that
  top-level field. This was an incorrect validation-script assumption, not
  a newly discovered runtime defect. Corrected the command to report missing
  duration explicitly, without treating absence as proof. Recheck PASS
  (`worker-evidence-rechecked.log`): all four frozen packs fail both current
  `sustain_duration` and `exact_rc_artifact` gates. Run 5 records 90.17s;
  run 6 records 90.43s; minimum is 14400s. The two older packs lack top-level
  duration. SHA-256 identities are recorded in that log. Raw evidence unchanged.
- Reachability confirmed: `maistro_server/main.py:542` installs the tested
  `RateLimitMiddleware`; `api/tasks.py:117` maps canonical admission ceiling
  rejection to 429; `pg_learnings.py:140` fences startup DDL in a transaction.
  These checks are not two-replica sustained execution evidence.

## Acceptance disposition

| Criterion | Fresh evidence / remaining requirement |
|---|---|
| Representative RC load profile | PARTIAL. Profile defines mix and thresholds but explicitly lists omitted users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background activity (`m3a-load-profile.md:152`). Representative completeness UNVERIFIED. |
| Two application replicas | Reference Compose defines two services; config/startup tests pass. Actual two-replica exact-RC deployment UNVERIFIED. |
| Sustained saturation, queues, leases, retries, leaks, shutdown | Historical packs rejected by executed evaluator; no qualifying new load run. UNVERIFIED. |
| Exactly-once/fenced physical work and Goal reconciliation | Admission-oracle and backpressure tests pass; they do not execute physical Attempts across replicas or reconcile Goals. UNVERIFIED. |
| Concurrent security/degraded behavior and replica-selection non-bypass | NOT MET: real middleware regression gives the same identity `[200,200,429]` independently on each replica, for authenticated and unauthenticated cases (`test_soak_promotion_gates.py:480-486`). Full security/degraded soak UNVERIFIED. |
| Required telemetry and explicit thresholds | Live child resource sampler regression passes; application-loop lag, complete worker census, sustained pool saturation and long-window observations UNVERIFIED. |
| Kill/restart during active work, drain/fencing/recovery | Config policy and sampler tests cannot prove physical recovery. UNVERIFIED. |
| >=4h exact RC artifact/configuration | Current runner always rejects its own topology (`run_soak.py:635-646`). Four historical packs rejected. UNVERIFIED. |
| Findings filed/reclassified at earliest invariant | Existing local F1–F12 classifications retained. No new load finding claimed. External filing UNVERIFIED; GitHub mutations prohibited. |
| Human/machine evidence with exact hashes | Historical pack hashes freshly recorded in validation log, not a new soak. Qualifying production-artifact evidence UNVERIFIED. |

## Final handoff

**BLOCKED.** No outstanding vulture repair reproduces at this head. The old H3
shared-store assertion is already corrected; rewriting it again would be cosmetic.
No code, runtime configuration, tests, policy, grants, ledger or historical raw
evidence was changed. Only this validation/handoff report was added.

No production soak was launched: the assignment does not identify the immutable
RC image/configuration selected for #89, and the existing runner is not a
production Compose runner. A longer emulator run cannot resolve this blocker.
The release owner must select the exact artifact/configuration, resolve the
replica-selection rate-budget mismatch, and provide a representative production
runner with physical Attempt/fence/recovery oracles and complete telemetry. Then
execute a new >=14400-second soak; any code/runtime-config change requires another.
Do not interpret this local writer handoff as integration approval.

Checkpoint: checked 1 assigned item, done 0 acceptance-complete issues, skipped 0,
errors 0 unresolved validation-command errors (one script assumption corrected).
Next: release prerequisites and genuine exact-RC soak, not another ledger edit.
The report is committed locally; commit identity is returned in the final response.
