# Issue #860 — bounded repair checkpoint (801fbaf9)

## Scope and observed state

Only issue #860; assigned branch `auto-860`, clean starting HEAD
`79e04d843e0dab9cf31b01e1eee291e73a1d6602`, supplied base
`af799688335f9a7dba7999a05e0e13f102c6c5ae`. No conflict or incoming
uncommitted work. The frozen scope is in the job's `worker-scope.md`.
No current-job `check-*.log` files were supplied. Read the dispatch snapshot,
previous result, and referenced `98a11313.../check-3.log` rather than assuming
prior validation claims. That historical failure expects 21 schema statements
and observes 24; the current test is independently rerun below.

## Fresh validation

Logs are in `/home/dev/maistro/jobs/801fbaf9290a4e9e82db2117a04ee3cf/`.
Commands have 600–1,200-second timeouts.

- Exact CI vulture command: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0;
  1,328 findings / 1,328 reviewed identities; zero unclassified or
  never-allowlist. Trusted base reported by gate: `72f5dedd3db3`.
  There is no evidenced identity to add/remove; ledger left unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped. Historical CI failure does not reproduce;
  no speculative schema repair. Current independent assertion includes all
  24 DDL statements, including Gauntlet columns (test lines 175–177), inside
  the advisory transaction fence (production lines 215–216). Fake-connection
  tests are not live PostgreSQL concurrent-boot proof; skipped cases remain
  unverified.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q`: 66 passed (65 soak gate cases, one server backpressure case).
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0; 3,159 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: exit 0; deployment
  stance components/backends exist (not live deployment proof).
- `uv run python scripts/check-backlog-consistency.py`: exit 0; 168 items.
- `uv run python` importlib evaluation of current `failed_promotion_checks`
  against `docs/testing/soak/evidence/m3a-round30-shakedown.json`: asserted
  rejection for `sustain_duration` and `exact_rc_artifact`; exactly those
  failures returned. Also asserted current `preflight_artifact_check().ok`
  is false. Recorded in `worker-artifact.log`.
- `git diff --check`: passed.

## Architecture reconciliation

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383
(Attempt fencing), ADR-082526-b36a (later TTL renewal/reclaim contract), and
ADR-085 (principal rate limits). ADR-081 deployment proposal is not accepted
permission to waive the issue. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; no competing scheduler, store, recovery or authorization authority.
Reclaim already has an accepted contract: missing sustained production evidence
must not be misreported as missing architecture.

## Acceptance review and disposition

| Issue criterion | Fresh evidence / remaining limit |
|---|---|
| Representative release workload | **UNVERIFIED**. `m3a-load-profile.md` explicitly omits concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained Goal/background reconciliation. Selected immutable RC/configuration not supplied. |
| At least two production replicas | **UNVERIFIED** on this candidate. Executed ASGI tests are not deployed replicas; runner explicitly identifies host preflight. |
| Sustained saturation, queues, expiry/reclaim, retries and leaks | **UNVERIFIED**. Historical evidence fails duration; no new long production run. Sampler regression really measures child allocation/FD growth but is not long-window evidence. |
| No duplicate physical work / canonical reconciliation | **UNVERIFIED**. Admission tests require canonical receipt identities, not physical-work uniqueness. Profile says schedule race cancels its queued probe Run without execution. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not established**. Executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) observes `[200,200,429]` separately on both middleware instances for the same identity. Middleware documents independent allowances (`api/rate_limit.py:31`) and is installed in production (`main.py:648`). Local enforcement/backpressure tests pass; they do not establish cluster-budget non-bypass. |
| Full production telemetry with thresholds | **UNVERIFIED**. Profile has preflight metrics/thresholds but driver-loop latency is not application-loop latency; worker/pool/reclaim/long-window evidence remains absent. |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED**. No new RC active-work restart; process rejoin/terminal totals cannot prove no loss or duplicate physical work. |
| Long exact-RC soak, invalidated by changes | **UNVERIFIED**. Current artifact function (`run_soak.py:730`) always rejects host preflight. Executed historical evaluator rejects artifact and duration. |
| Findings filed/reclassified to earliest milestone | **UNVERIFIED** completeness. Blockers recorded locally; no GitHub mutation authorized/performed. |
| Machine/human evidence bound to image/package/commit/config | **UNVERIFIED** for this candidate. This report and logs document focused checks, not an exact-RC attestation. |

**BLOCKED for issue acceptance**, not a reproduced CI/schema/vulture failure.
Only this report changed. No production changes, tests, inventory delta,
ledger/grant changes or gate weakening. No merge needed: initial tree had no
conflict. No GitHub mutations or pushes. Existing inherited changes preserved;
focused checks do not certify the entire inherited branch diff.

Next required input/action: select the immutable promotion RC/configuration,
complete the representative workload, reconcile replica-budget semantics,
then execute the >=4-hour exact-artifact soak and active-work restart with
canonical physical-work/reclaim and full telemetry evidence. Another short
host preflight or identical CI-only repair cannot close these gaps.

Checkpoint: checked 1 issue, done 0, skipped 0, validation errors 0, blocked 1.
This report is committed locally for handoff, not integration approval.
