# Issue #860 — job d9d97579 validation handoff

Scope was frozen to issue #860 and its assigned vulture-ledger check. The
starting worktree at `a800d86be627908f0db072d2f3c3c80cfe889f0e` was clean.
No `check-*.log` files exist in the supplied job directory. The prior result
was read and independently checked; no stale CI finding was accepted without
fresh evidence. No GitHub actions were taken.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1,315 reviewed identities match 1,315 findings; 0 unclassified and 0 never-allowlisted. No ledger amendment is warranted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS: 84 passed in 1.72s. These are deterministic gate tests, not production acceptance.
- `docs/testing/soak/evidence/m3a-round109-shakedown.json` records `sustain_seconds: 420.05`, `exact_rc_artifact.ok: false`, and topology `host-uvicorn-preflight`. Both duration and exact-artifact requirements fail (profile minimum: 14,400 seconds).
- `scripts/soak/run_soak.py:744-754` deliberately returns `ok: false` for the host-process preflight; it cannot issue promotion evidence for a Compose image/configuration.
- `docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile gaps” and “Round-2 amendments”, explicitly leaves representative user/Workspace and workload coverage, physical Attempt fencing/recovery, sustained reconciliation, application-level telemetry, worker/pool/reclaim measurements, and long-window observations unproven.
- Accepted ADR-062 preserves the canonical graph execution model. ADR-085 specifies rate limiting per principal, but does not establish a shared cluster-wide counter; the documented local limiter evidence therefore cannot prove replica-selection non-bypass. No alternative scheduler, execution authority, or authorization path is proposed.

## Acceptance disposition

- Representative exact-RC workload and at least two production replicas — **UNVERIFIED**; no selected immutable RC/configuration or qualifying production deployment evidence is supplied.
- Four-hour sustained multi-replica load, saturation/queue/reclaim/retry/leak/shutdown observations — **UNMET/UNVERIFIED**; available round-109 evidence is a 420.05-second preflight only.
- No duplicate physical work, Goal reconciliation and kill/restart fencing/recovery — **UNVERIFIED**; the schedule probe does not execute the admitted Run, and terminal counts do not prove physical Attempt fencing.
- Security/rate-limit non-bypass under replica selection — **UNVERIFIED**; per-principal process behavior does not show a shared replica budget.
- Required telemetry, thresholds, and findings disposition — **UNVERIFIED** at RC grade; no qualifying evidence pack tied to promoted artifact/configuration hashes.

This worktree cannot honestly certify promotion or manufacture operational evidence. Remaining acceptance requires the owner to designate the immutable RC and configuration, close the documented workload/telemetry/physical-effect evidence gaps, then run the unchanged >=14,400-second production-topology soak and publish artifact-bound machine/human evidence. No tests were added; no suite-inventory delta applies. Vulture passed, so no ledger edit is made.

Disposition: **BLOCKED for acceptance**; no production/code repair justified by the inspected evidence. Local commit is a validation handoff, not integration approval.
