# Issue #860 acceptance validation — job 1ec6de12

## Scope and starting state

Validated only issue #860 at starting commit `9b07bcfb3efd79fa53472e3d8dd2f872232ab3d4` on branch `auto-860`. The worktree was clean. No `check-*.log` files were supplied in the job directory; the prior result artifact recorded `BLOCKED`, and its claims were checked against the current tree rather than treated as proof. No tests or runtime code were changed in this validation.

## Executed checks

- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3404 files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1321 findings match 1321 reviewed identities; zero unclassified or never-allowlisted findings. No ledger edit justified.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` — PASS, 92 tests.
- `uv run python scripts/check-suite-inventory.py` — PASS, 21 suites / 33051 unique test identities.
- `uv run python scripts/check-backlog-consistency.py` and `uv run python scripts/check-adr-index.py` — PASS.
- Evaluator probe against `docs/testing/soak/evidence/m3a-round109-shakedown.json` — `failed_promotion_checks` returns `sustain_duration` and `exact_rc_artifact`; observed 420.05 seconds, not the required 14400. The evidence hashes identify `5a59c724a20ef1241d57c048df90758f2c2e1e25`, not this starting commit. `preflight_artifact_check()` returns false with topology `host-uvicorn-preflight`.
- `docker compose -f deploy/docker-compose.prod.yml ps` — BLOCKED before startup: Compose interpolation requires `REPLICATION_PASSWORD`, which is not set in this environment. No production Compose run was performed here.

## Acceptance review

| Criterion | Evidence / disposition |
|---|---|
| Representative release-candidate workload | PARTIAL / UNVERIFIED: `m3a-load-profile.md` defines a preflight request mix, but its “Remaining representative-profile gaps” explicitly says there is no concurrent population of users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas workload, or Goal/background-worker reconciliation. |
| At least two production replicas | UNVERIFIED in this validation: the production stack could not start because `REPLICATION_PASSWORD` was unset. |
| Sustained saturation, reclaim, retry, leaks, and restart observations | NOT MET: round109 is 420.05 seconds; the promotion evaluator requires 14400 seconds. The host process run is not an exact-RC soak. |
| Exactly-once admission/reconciliation and physical-work fencing | UNVERIFIED at promotion grade. Existing probe/test assertions cover selected admission and claim seams, but do not establish sustained Goal reconciliation or physical Attempt fencing under production multi-replica load. Accepted ADR-081626-f383 makes the canonical lease/fencing token authoritative; a Run count alone is not physical-work proof. |
| Rate/security/degraded behavior under concurrency without replica-selection bypass | UNVERIFIED for the requested guarantee. The profile explicitly says its process-local rate enforcement does not prove a cluster-wide budget or prevent aggregate allowance from scaling with replica selection. |
| PostgreSQL, event-loop, worker, RSS, descriptor, queue, and error telemetry with thresholds | PARTIAL: profile has thresholds and a preflight sampler, but the required complete long-window production telemetry was not collected here. |
| Kill/restart with graceful drain, fencing, and recovery | UNVERIFIED here; no production restart was executed. |
| At least four hours on exact RC artifact/config | NOT MET: round109 is short and has `exact_rc_artifact.ok=false`; current host-preflight code deliberately cannot attest the Compose artifact. |
| Load findings filed/reclassified to earliest broken invariant | UNVERIFIED; no issue/PR actions are authorized or performed. |
| Machine-readable and human-readable evidence tied to immutable RC/config hashes | NOT MET for this candidate: the available evidence belongs to another commit and no immutable RC/configuration was exercised in this validation. |

## Governance and disposition

The canonical execution authority remains `Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing scheduler, store, event authority, or authorization path was added. ADR-081626-f383 is accepted and requires fencing for production Attempt writes. ADR-073126-c4e1 requires an RC candidate to be soaked on `develop`; an emulator run is not equivalent to that candidate. ADR-081 is Proposed and does not waive the issue criteria.

**Disposition: BLOCKED for #860 acceptance.** Deterministic tests and static gates pass, but they do not establish the required four-hour exact-RC production soak, full workload coverage, or replica-resistant rate-limit guarantee. No test was added, so no inventory delta is required. Next work requires production Compose secrets/configuration, a frozen immutable RC, a full representative workload and ≥4-hour instrumented run, and an owner decision on rate-limit semantics.
