# Issue #860 repair — job 186977cd

## Frozen scope

- Assigned issue: #860 only; branch/worktree: `auto-860` in `/home/dev/Git/wt/auto-860`.
- Verified starting HEAD: `d664e6d42feb7e31be240c24d7bab264d70bcc99`.
- Verified supplied base: `680329c960cd722034bd0053be745f3de138ba8d`.
- Starting worktree clean; no incoming changes to salvage.
- Job directory has no `check-*.log` files. Prior result is available and reports BLOCKED; its claims require fresh validation.
- Process only the issue snapshot supplied in the prompt. No remote enumeration or mutations.
- Inspection scope: repository instructions; relevant execution, recurrence, fencing, deployment, telemetry and rate-limit ADRs; `scripts/soak/run_soak.py`; its promotion tests and load profile/evidence; adjacent production rate middleware, task admission, PostgreSQL learnings code/tests; production Compose; exact vulture checker/workflow/ledger.
- Allowed repair targets: actual dead-code identities reported by the exact scanner and reviewed retained identities in `quality/vulture-baseline.json`; demonstrably broken issue-860 code/tests if discovered; this handoff and inventory notes if tests change. No speculative gate edits.

## Assumptions and limits

This is the writer/CI-repair lane. A qualifying long soak requires the exact promotion artifact/configuration, a representative production workload and all required telemetry. A host preflight is not a substitute. Missing artifact selection or acceptance evidence will remain explicitly UNVERIFIED, not be repaired through a ledger edit or a passing unit test.

## Progress

- `uv sync --locked --extra dev`: PASS (204 packages checked).
- `RATCHET_BASE_REV=680329c960cd722034bd0053be745f3de138ba8d uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1342 reviewed identities, 1342 findings, zero unclassified/never-allowlist findings. The checker resolves supplied base through merge-base (`928993dda1c9`). No actual unbanked identity exists to repair; leave the ledger unchanged rather than invent a finding.
- Architecture review: accepted ADR-081426-1f7c assigns physical execution identity to Attempt; accepted ADR-081626-f383 keeps fencing authority in the canonical Run store; ADR-085 requires per-principal rate limiting. ADR-081 is Proposed, not an accepted waiver. The load profile explicitly identifies the runner as host-process preflight and lists incomplete workload coverage. No execution/authorization authority will be added or bypassed.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2891 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 88 passed, 5 skipped in 3.09s. Database-backed learnings tests skipped; not PostgreSQL soak evidence.
- `git diff --check 680329c960cd722034bd0053be745f3de138ba8d...HEAD` and `git diff --check`: PASS; previous EOF-whitespace findings do not reproduce at this head.
- Production middleware tests reproduce independent replica allowances for both authenticated and pre-auth identities (`tests/test_soak_promotion_gates.py:439-488`); these tests pass because they assert the limitation, not because a shared budget exists. Direct-burst 429 tests cannot prove non-bypass by replica selection.
- Accepted ADR-082426-82c7 binds schedule occurrence uniqueness to canonical Run persistence. ADR-082526-b36a adds heartbeat/expiry/reclaim semantics to Attempt fencing; neither a raced admission nor process restart alone proves physical-work recovery. ADR-083026-a91e forbids treating unmeasured telemetry as zero. Those remain constraints on future qualifying load evidence.
- `uv run pytest packages/maistro-server/tests -x -q`: 494 passed, 8 skipped, 22 deprecation warnings in 50.23s. This covers the server package, not a multi-replica deployment.
- `uv run python scripts/check-ratchet-provenance.py`: PASS (49 quality JSON consumers; delegated provenance gates pass).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `uv run python scripts/check-deployment-claims.py`: PASS.
- Fresh inline Python imported the current runner and evaluated `evidence/m3a-round6-shakedown.json`: asserted failed checks are exactly `sustain_duration` and `exact_rc_artifact`. The evidence names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head; observed duration is 90.43 seconds. The current artifact check reports `ok=false`, topology `host-uvicorn-preflight`. Historical stored booleans are not newly observed production behavior.

## Acceptance audit

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative release-candidate profile | PARTIAL: read `m3a-load-profile.md`, compared with `deploy/docker-compose.prod.yml`. Profile lists request mix and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. Complete representative profile UNVERIFIED. |
| At least two production application replicas | UNVERIFIED: Compose declares two, but no exact-image Compose load run executed. ASGI middleware instances and historical host processes do not prove this criterion. |
| Sustained saturation, queues, reclaim, backoff, leaks, shutdown | UNVERIFIED: current evaluation rejects the historical 90.43-second window against 14400 seconds. Unit/process-sampler tests are not sustained production measurements. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | UNVERIFIED: historical occurrence admission is one raced occurrence, followed by cancellation; no physical Attempt execution/fencing or sustained Goal reconciliation proof. Current admission-probe tests check receipt integrity, not physical effects across production replicas. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared per-principal allowance: executed production-middleware tests reproduce `[200, 200, 429]` independently on each instance for the same identity. Local enforcement and backpressure tests pass; production-load security/degraded evidence remains UNVERIFIED. No second authorization path was introduced to mask this mismatch. |
| Required telemetry with explicit thresholds | PARTIAL: real child-process RSS/descriptor sampler regression passes; application-loop latency, detached workers, qualifying PostgreSQL saturation/query/lock series, queue and timeout rates remain UNVERIFIED. Driver loop lag is not application loop lag. |
| Kill/restart during active work with fencing/recovery | UNVERIFIED: historical process rejoin and terminal counts do not observe physical effects. No qualifying kill/restart performed in this round. |
| Long soak of exact RC artifact/configuration | NOT MET: current runner cannot produce exact-RC proof even for four hours; fail-closed CLI tests pass. No promotion artifact/configuration was selected in the assignment beyond code refs. Do not spend four hours rerunning a structurally ineligible preflight. |
| Findings filed/reclassified to earliest broken milestone | PARTIAL: local backlog has dispositions and consistency gate passes; external filing/reclassification and completeness UNVERIFIED. GitHub mutation is prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | PARTIAL: historical evidence exists and is preserved; no qualifying current RC evidence. This document records validation, not a soak attestation. |

## Disposition and handoff

**BLOCKED.** The requested exact-debt-ledger failure and prior whitespace errors do not reproduce. No source, runtime configuration, tests, inventory or ledger changed; only this evidence/handoff document was added. With no test-count delta, no inventory note is needed. Gates were not weakened and historical evidence was not rewritten.

The previous BLOCKED state cannot be resolved by cosmetic edits or speculative ledger banking. Next work needs an explicitly selected immutable RC image/configuration, a production-topology runner and workload that covers the missing surfaces, observability of physical effects and lease recovery, resolution of the replica-selection rate-budget gap, and a new uninterrupted qualifying soak after any runtime change. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and canonical admission/fencing authorities throughout.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "qualifying production RC soak prerequisites; issue #860 remains blocked"}`. Local validation completed; issue acceptance is not complete. Commit this handoff locally; no push, PR, issue comment or closure.
