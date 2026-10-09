# Issue #860 — repair checkpoint (job 3528180f)

## Frozen scope

One item: issue #860 on `auto-860`, starting at
`817a5d877dec8474b773b5d43be52c5b0a3d7f20`; supplied develop base
`c0441cf94b9a8e58517da0f4159070b97ea6a706` resolves. Initial worktree clean.
No sync conflict exists; no remote mutation or ref refresh is needed.

Review scope is fixed to repository instructions, relevant ADRs, production
Compose/rate-limit contracts, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, the existing pg-learnings and task
backpressure tests, `docs/testing/soak/{m3a-load-profile,m3a-soak-evidence}.md`,
round-6 evidence, CI gate definitions and the supplied prior job result.
Permitted changes: evidence-backed corrections in those soak documents/gates,
the corresponding inventory note if tests change, this checkpoint, and the
vulture ledger only if the required scan identifies retained unbanked debt.

## Current executed results

- Required exact vulture scan: PASS, 1,345 findings / 1,345 reviewed identities,
  zero unclassified or never-allowlist findings. No ledger amendment warranted.
- Job directory contains no `check-*.log` files at initial inspection. Supplied
  earlier green driver checks are not current validation evidence.
- Profile explicitly limits the runner to a host-process preflight, requires
  >=14,400 sustained seconds on exact production images/configuration, and
  acknowledges missing representative workloads and physical-work proof.

## Review checkpoint

- Prior job result read: BLOCKED, not approval. Its ending head matches this
  lane's supplied starting head.
- The reported shared-rate-store contradiction is already corrected in the
  current evidence pack (H3 and remaining-blocker item 4). Production middleware
  still uses independent in-memory limiters per instance. Do not change #842's
  contract or invent a second authorization path to satisfy a soak assertion.
- Accepted ADR-081226-a66b preserves Run -> NodeRun -> Attempt authority;
  accepted ADR-081626-f383 requires durable fencing and explicitly leaves
  lease-expiry takeover undefined. Admission uniqueness or process rejoin is
  not proof of physical execution uniqueness/reclaim. ADR-081 is Proposed,
  not accepted authority to override those constraints.
- Production Compose requires an external reachable model gateway and builds
  the application image locally; the preflight uses host uvicorn and absent
  model service. They are not interchangeable artifacts.
- Inspected the gate tests: real production middleware instances demonstrate
  independent allowances; mock HTTP probes test oracle completeness; a live
  uv child tests process-group resource observation. None is a production soak.
- Round-6 raw evidence records 90.43 sustained seconds against a 14,400-second
  minimum. Its apparent functional pass is historical, not current RC proof.

## Assumptions / next action

Writer lane (explicit assigned repair and local commit requirement). No immutable
RC image/configuration was supplied. Do not invent one or sign promotion from a
host emulator. Verify the reported contradiction and fail-closed gates, perform
focused validation, then record remaining acceptance blockers and commit.

## Final validation (this job, not inherited claims)

All commands ran in the assigned worktree with long timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,345 reviewed / 1,345 current.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q`: **80 passed, 5 skipped**, 2.37 s. Skips are not acceptance evidence. Includes real production middleware allowance tests and the live process-group sampler test; no production database or replica soak is claimed.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,859 files already formatted.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 46 consumers have explicit provenance; delegated checks pass. Non-fatal invalid-escape and local HTTP CORS warnings emitted.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python -` imported the actual soak runner and evaluated the fixed
  round-6 JSON path with `failed_promotion_checks`: failed checks are exactly
  `sustain_duration` and `exact_rc_artifact`. Assertions confirmed observed
  duration < minimum and both required rejection reasons.
- `git diff --check`: PASS.

The ratchet tools resolved their own base to `1e4933e2a1b7`, not the supplied
historical develop base. Results above describe those exact tool invocations,
not a claim of approval relative to another base. No ledger/grant edits made.
No tests changed or added; no inventory delta is required.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED: profile inspection shows one key, no multi-Workspace population, Graph fan-out, successful tool/model or Design/Canvas workload. Applicability requires selected RC configuration. |
| At least two supported application replicas | Historical host-replica run inspected; two exact-RC Compose replicas UNVERIFIED. |
| Sustained saturation, queue growth, expiry/reclaim, retry and leak observation | UNVERIFIED: observed 90.43 s; no new long-window workload run. |
| Schedule/task/Run/Attempt uniqueness and Goal reconciliation | Admission-oracle tests pass; physical-work uniqueness, sustained schedules, reconciliation and recovery UNVERIFIED. No competing execution authority introduced. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | NOT MET: real production middleware tests show two fresh allowances for the same identity on separate replicas; six-path rejection is not a shared budget. Broader RC security/degraded behavior UNVERIFIED. |
| Full telemetry and explicit thresholds | Sampler regression passes; application-loop latency, worker census, pool saturation, lock/queue/error thresholds over an RC window UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | Historical process exit/rejoin is insufficient; correlated physical Attempts and effects across restart UNVERIFIED. |
| >=4-hour exact RC artifact/configuration soak | NOT MET: current gate rejects round-6 evidence for duration and artifact; host runner always rejects exact-artifact certification. No immutable RC identity supplied. |
| Findings filed/reclassified to earliest invariant | Local F11/F12 M3-A evidence-validity classifications inspected. External filing UNVERIFIED; GitHub mutation forbidden. |
| Human/machine evidence bound to image/package/commit/config hashes | Historical packs inspected, not current production proof. Exact promoted artifact/configuration evidence UNVERIFIED. |

## Handoff

**BLOCKED** on RC selection and the missing production-artifact soak/profile,
plus unresolved replica-selection rate-limit acceptance. The initial reported
shared-store documentation defect is already repaired; current scan evidence
requires no dead-code or ledger change. Do not manufacture scanner findings,
weaken gates, or rerun a four-hour host emulator as a substitute.

Changed file: this checkpoint only. Existing implementation, historical evidence,
and all previous handoffs preserved. Next owner must supply the immutable RC
image/configuration, resolve supported workload and rate-budget scope, then run
and publish the production-topology soak with physical-work/telemetry proof.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; command errors 0;
blocked 1. Local commit records this review; it is not integration approval.
