# Issue #860 — repair round 890a8510

## Frozen scope

- Sole item: issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `68f19bb0492b6ae9edc82a7afaa97434f96ac5f9`; supplied develop base: `ce19fd99e40503185a3a3890a7bdf259d7c998ab`.
- Initial working tree clean. No incoming work to salvage.
- Inputs frozen to this job's `dispatch-context.json`, supplied prior result (if present), and repository state. No GitHub mutation or re-enumeration.
- File scope: this report; `quality/vulture-baseline.json` only for actual scan-proven retained identities; source/test files only if the scan demonstrates a genuine issue in the assigned soak implementation. No unrelated debt repair.
- Assumption: this is the explicitly authorized exact-debt-ledger repair round, not authorization to substitute local shakedowns for final promotion evidence.

## Progress

- Confirmed assigned HEAD and clean initial state. Job directory has no `check-*.log` files; validation must be executed locally.
- Exact requested vulture command executed successfully: 1,336 findings match 1,336 reviewed identities; zero unclassified and zero never-allowlist findings. No ledger amendment or source removal is justified by this scan.
- Supplied prior result read; it reports the same passing scan and unresolved production acceptance. Independently read the current profile: it explicitly describes a host-process preflight, not an exact production artifact, and lists representative-workload gaps.
- Attempted prior report path `issue-860-7d8dc6e8-repair.md` was not found; skipped. The supplied prior result JSON was available.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (3,003 files). `git diff --check ce19fd99e40503185a3a3890a7bdf259d7c998ab...HEAD` passed; the older reported whitespace failure is not reproduced against this assigned base.
- Inspected accepted ADR-081226-a66b (canonical lifecycle) and ADR-081626-f383 (durable Attempt fencing). Admission identity is not physical-work proof; lease-expiry takeover must not be invented by the soak driver. ADR-081 is Proposed, not an accepted waiver of the issue's deployment acceptance. No competing execution/authorization authority will be introduced.
- Current `RateLimitMiddleware` creates an `InMemoryRateLimiter` per instance. Existing adjacent tests exercise the real middleware on two ASGI apps and assert independent allowances. This is a reproducible counterexample, not evidence of a cluster-wide limit.
- Focused validation: `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — **75 passed in 3.38s**, including both authenticated and unauthenticated independent-replica allowance counterexamples.
- `uv run python scripts/check-ratchet-provenance.py` passed (49 consumers with explicit provenance); `uv run python scripts/check-shipped-surface-truth.py` passed. The gates selected trusted base `56332162cf63`; this is distinct from the supplied develop base used for the whitespace check, and no provenance settings were overridden.
- Loaded the real driver with `importlib` and evaluated `docs/testing/soak/evidence/m3a-round6-shakedown.json`: actual duration **90.43 seconds**, current minimum **14,400 seconds**, rejected checks **sustain_duration, exact_rc_artifact**. `preflight_artifact_check()` returned `ok=False`, topology `host-uvicorn-preflight`.

## Acceptance audit

| Issue criterion | Executed evidence / disposition |
| --- | --- |
| Representative release-candidate workload | **UNVERIFIED**. Read current profile, lines 152–160: one API key; user/Workspace population, Graph fan-out, successful tools/models, Design/Canvas and reconciliation absent. |
| At least two application replicas | **UNVERIFIED for the RC**. Production Compose declares two services; executed ASGI tests use two middleware instances, not deployed images. |
| Sustained saturation, reclaim, retry, leaks and restart | **UNVERIFIED**. Current evaluator rejects the 90.43-second historical shakedown. No new long-window run performed. |
| No duplicate physical work, schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED**. Profile lines 197–200 explicitly distinguish an admission race from physical execution and sustained reconciliation; canonical accepted fencing ADR does not permit substituting admission counts for physical-work evidence. |
| Replica-selection-safe rate limiting/security/degradation | **Counterexample reproduced**. `tests/test_soak_promotion_gates.py:439–489` passes against production middleware: first replica returns 200,200,429, and the second permits another 200,200 before 429 for the same identity. Other local limiter/backpressure tests pass, but cannot establish the stronger multi-replica acceptance. |
| Full PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry with thresholds | **UNVERIFIED**. Profile acknowledges driver-loop timing is not application-loop timing and required worker/long-window observations are absent. |
| Kill/restart during active physical work with fencing/recovery | **UNVERIFIED**. Process rejoin/Run counts are insufficient; no active-work production restart executed this round. |
| Long soak of exact RC image/configuration | **UNVERIFIED**. Current driver explicitly rejects its host-process topology; the actual historical evidence fails both duration and artifact checks. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED for complete load coverage**. Existing finding references do not prove complete classification; no GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED for current RC**. Historical evidence is retained, not relabeled as current evidence. This report records validation, not a promotion soak. |

## Outcome and handoff

**BLOCKED** for issue acceptance. The requested exact-debt-ledger failure is not reproducible; do not amend a matching ledger or remove retained APIs merely to manufacture a change. Only this report changes. No production code, tests, inventory counts, grants or ledger changed, so no inventory-delta note is required.

Next prerequisites: select the exact immutable RC image/configuration and representative production workload; resolve the replica-selection budget contract through the canonical limiter path; execute the production topology for at least four hours with application telemetry and physical Attempt fencing/restart observations. Any resulting code/runtime-config changes require a fresh soak. Extending the host preflight cannot satisfy this.

Checkpoint: one assigned item checked, zero acceptance-complete items, one blocked item, zero reproduced CI-gate failures. Local report commit required; no push or integration approval.
