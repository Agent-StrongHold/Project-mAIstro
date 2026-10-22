# Issue #860 validation — job 63901fe0

Validation performed against `5627b0042d82855924ddadd8bd6e90e21152038e`.
This note records a re-check; it does not claim promotion readiness.

## Commands and observed results

- `uv run python scripts/soak/run_soak.py --help` — passed; driver documentation and CLI identify the runner as host-process preflight and state that it cannot sign promotion evidence.
- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — 84 passed.
- `uv run pytest tests/test_soak_promotion_gates.py -k replica_selection -q -x` — 2 passed, 82 deselected. These tests demonstrate that each process has an independent bucket; exhausting one replica's allowance leaves the same identity another allowance on another replica. This does not meet issue criterion 5.
- The assigned job directory contains no `check-*.log` files, so no driver logs were available to independently inspect. The prior verifier result at `/home/dev/maistro/jobs/654d47296be24329a29f8a668abfca50/result.json` was treated only as a lead, not as validation evidence.

## Acceptance status

- Representative load profile: **not met**. `docs/testing/soak/m3a-load-profile.md` (Remaining representative-profile gaps) calls out single user/Workspace, absent Graph/tool/Canvas/Goal/background-worker traffic, and missing production-grade pool/worker/fencing observations.
- Two production replicas: **unverified**. Existing evidence uses the host-process preflight, not the production Compose image/config.
- Four-hour sustained exact-RC soak: **not met**. `m3a-round109-shakedown.json` records `sustain_seconds: 420.05`; `scripts/soak/run_soak.py::preflight_artifact_check` hard-codes `ok: false` for host processes.
- Cross-replica rate-limit resistance: **not met**. `packages/maistro-server/src/maistro_server/api/rate_limit.py` creates an `InMemoryRateLimiter` per middleware instance. The two tests above confirm replica selection provides an independent allowance. This behavior agrees with its documented process-local policy, but does not prove the stronger issue acceptance criterion.
- Physical-work fencing, telemetry thresholds, kill/restart production drain/recovery, and finding reclassification: **unverified** at the exact production artifact/profile.
- Machine/human evidence tied to exact RC/config hashes: **not met**; the available shakedown is not exact-RC evidence.

## Governance reconciliation

The accepted ADR-081626-f383 execution-lease contract assigns durable lease/fencing authority to the canonical Run store and AttemptExecutionService; process restart or a stale-write fence alone is not proof that physical work did not duplicate. ADR-085 specifies per-principal rate limiting, while the implementation explicitly documents per-process enforcement. These contracts do not waive the issue's requirement for observed multi-replica evidence. No architecture or policy changes were made in this validation.

No four-hour soak was launched: the available harness cannot produce exact-RC promotion evidence, and running a longer host preflight would not establish acceptance.
