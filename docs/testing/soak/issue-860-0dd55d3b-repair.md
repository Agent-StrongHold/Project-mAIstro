# Issue #860 — repair validation, job 0dd55d3b

## Frozen scope and findings

Only issue #860 in assigned `auto-860` worktree. Starting HEAD:
`d60112636552b72718531075dd25df130712f639`; supplied base:
`af799688335f9a7dba7999a05e0e13f102c6c5ae` (verified to resolve).
Initial tree clean. No salvage needed; no remote mutations or ref refresh.
Input snapshot: supplied dispatch context, prior result 20a7fa3f and historical
98a11313/check-3.log. Current job directory contained no driver check logs.
Writer assignment takes precedence over generic verifier wording.

The prescribed vulture check was executed afresh and passed: 1,328 findings,
1,328 reviewed identities, zero unclassified/never-allowlist. Its reported trusted
base is `72f5dedd3db3`, not the supplied develop tip. No unbanked identity exists
to justify deleting production code or amending the ledger in this round.

Historical check-3 failed because the learnings schema-fence test expected 21
statements but production executed 24. Current test independently lists the
additional Gauntlet columns; focused execution passes, so that failure no
longer reproduces. Existing soak profile explicitly disclaims exact
RC equivalence and representative-workload completeness. Neither previous
reports nor a green static gate establish release acceptance.

## Validation

Executed afresh; full logs retained under
`/home/dev/maistro/jobs/0dd55d3b28d34bf3a58661f4dd218382/worker-*.log`:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed (1,328 reviewed identities). Arguments match `.github/workflows/vulture-ratchet.yml`.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3,159 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. This validates the current schema-fence statement contract, not live PostgreSQL concurrent DDL.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 65 passed, including production middleware replica-selection probes.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 1 passed.
- `uv run python scripts/check-backlog-consistency.py`: passed (168 items).
- `uv run python` importlib probe of current `run_soak.py` against historical `evidence/m3a-round30-shakedown.json`: asserted failures include `sustain_duration` and `exact_rc_artifact`; these were exactly the two returned failures. Also asserted current `preflight_artifact_check()['ok'] is False`. This evaluates old evidence; it is not a new soak.

## Architecture reconciliation

Read accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle) and
ADR-081626-f383 (execution lease/fencing). Preserve `Goal -> Graph -> Run ->
NodeRun -> Attempt`; the Run store remains execution authority. The lease ADR
explicitly does not define expiry takeover/recovery supersession. The soak issue
cannot authorize a competing scheduler or reclaim mechanism to fill that gap.
No runtime or authorization changes are justified by the reproduced checks.

## Acceptance: all ten criteria

| Criterion | Evidence / disposition |
|---|---|
| Representative users/Workspaces, fan-out, schedules, tools/models, Design/Canvas, workers | **UNVERIFIED** completeness. `m3a-load-profile.md` explicitly lists missing workloads; no exact RC profile was supplied for this round. |
| At least two supported production replicas | **UNVERIFIED** on this candidate. ASGI instances are not production replicas; current runner reports host preflight topology. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED**. Historical duration gate fails; no sustained production run performed. |
| No duplicate physical work across schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED**. Admission identity tests do not establish physical side effects or sustained reconciliation. |
| Rate/security/degraded behavior non-bypass by replica selection | **Not proven**: executed `tests/test_soak_promotion_gates.py:439` demonstrates the same principal gets independent `[200, 200, 429]` allowances on both production middleware instances. Production wiring: `maistro_server/main.py:648`. Backpressure test passes, but does not establish cluster non-bypass. |
| Complete production telemetry with explicit thresholds | **UNVERIFIED**. Profile distinguishes driver-loop lag from application-loop lag and acknowledges missing worker/pool/lease/long-window observations. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Process rejoin and terminal counts alone cannot establish absence of lost/duplicate physical work. |
| Long soak of exact RC artifact/config, rerun after changes | **UNVERIFIED**; current evaluator rejects historical round30 for both duration and exact artifact. Current host runner always fails exact-artifact gate (`run_soak.py:730`). |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED** completeness. Local blockers recorded; no GitHub mutation permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED** for current candidate. Existing historical evidence is not a current RC attestation. |

## Handoff

**BLOCKED** for issue acceptance, not by the requested vulture repair. No new
production defect was reproduced that warrants code or ledger changes. No tests
added or changed, so no inventory delta. Only this report changed.

Next owner must identify an immutable RC/configuration and execute a representative
production-path workload, resolve the replica-budget and reclaim contract gaps,
and collect physical-work/recovery observations during the long soak. A four-hour
host-emulator run cannot supply that evidence. This is not integration approval.

Progress: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
Local commit required before handoff; no pushes, issue actions or gate weakening.
