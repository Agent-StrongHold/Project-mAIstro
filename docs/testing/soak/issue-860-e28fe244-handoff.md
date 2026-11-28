# Issue #860 — repair validation e28fe244

## Scope and disposition

Checked only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`,
starting at verified clean HEAD `a3f1df7a7d46e922beaef5f5a4e02846bac31478`.
Dispatched base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
The supplied dispatch-context.json is the frozen issue/acceptance snapshot;
no GitHub refresh, mutation, merge, or push was performed.
The only edited file is this handoff. No runtime, test, grant, or ledger changes.
Test inventory delta is zero; no inventory note is required.

Assumption: the explicit vulture repair permits reconciliation of actual scan
findings, not speculative ledger changes. The exact scan passes, so there is
nothing to amend. The supplied historical failure is a different test failure
and no longer reproduces. Remaining production acceptance is **BLOCKED**.
Do not dispatch another unchanged vulture repair as a substitute for the missing
production soak work.

## Fresh validation

The current job directory contained no driver `check-*.log` files. Read the
specified historical `98a11313167b41a98a420abfda80c292/check-3.log`: it failed
`test_ensure_schema_fences_ddl_behind_advisory_lock` with 24 statements versus
21 expected. Current test explicitly includes the three Gauntlet audit columns;
the production column list includes them too. Fresh execution passed.
The prior result artifact was read, but its verification claims were not used
as executed evidence for this attempt.

Commands below ran in the assigned worktree with 1,200-second timeouts:

| Command | Fresh outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,322 reviewed identities match 1,322 findings; unclassified and never_allowlist both zero. Arguments match `.github/workflows/quality.yml:1079`. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q` | 109 passed, 6 skipped in 2.47s. Skips are not acceptance evidence. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,301 files already formatted |

These are focused deterministic checks, not a production deployment or soak.
No long-running load or live PostgreSQL recovery test was performed.

## Acceptance audit

| Criterion from issue snapshot | Evidence and remaining gap |
| --- | --- |
| 1. Representative RC profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` explicitly lists missing concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background workloads. Existing profile is not representative proof. |
| 2. At least two production application replicas | UNVERIFIED. `scripts/soak/run_soak.py:744` identifies the runner as host-uvicorn preflight, not the promoted Compose artifact. Middleware tests use two ASGI instances, not a production deployment. |
| 3. Sustained saturation/reclaim/retry/leak observations | UNVERIFIED. No sustained load executed; deterministic tests cannot establish this criterion. |
| 4. No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels the schedule admission probe Run without executing it. Admission cardinality is not physical Attempt uniqueness or Goal reconciliation evidence. |
| 5. Replica-independent rate/security/degraded enforcement | UNVERIFIED, with reproduced counterevidence for an aggregate allowance. Executed `tests/test_soak_promotion_gates.py:439`: both authenticated and unauthenticated identities get independent 200,200,429 sequences on two real middleware instances. Production registers this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; its constructor creates a local limiter at `api/rate_limit.py:93`. Local enforcement does not prove replica selection cannot increase an allowance. |
| 6. Production telemetry with thresholds | UNVERIFIED. `scripts/soak/run_soak.py:1433` measures driver-loop lag, not application-loop latency. Resource-sampler regressions passed, but no production series was collected here. |
| 7. Kill/restart during active work with fencing/recovery | UNVERIFIED. `scripts/soak/run_soak.py:1451` restarts a process group; subsequent terminal-Run counts do not establish side-effect uniqueness or active Attempt recovery. |
| 8. Long-running exact-RC soak | UNVERIFIED. Executed `test_four_hour_preflight_cannot_pass_cli` rejects missing/null/preflight artifact records. This proves fail-closed behavior, not an RC soak. No promoted RC image/configuration was exercised. |
| 9. Complete earliest-invariant findings disposition | UNVERIFIED. This handoff records local blockers; complete disposition has not been established. No issue filing or other GitHub mutation performed. |
| 10. Hash-bound machine/human soak evidence | UNVERIFIED at production grade. This source-head-bound validation report is not image/configuration-bound production load evidence. |

## Architectural reconciliation and next step

Read repository instructions, documentation authority hierarchy, and accepted
ADR-081426-1f7c (Attempt physical identity), ADR-081626-f383 (canonical-store
lease/fence authority), and ADR-073126-c4e1 (unchanged RC artifacts promoted).
The lease ADR explicitly does not define expiry takeover. The issue's reclaim
acceptance cannot justify inventing a separate recovery authority. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; use canonical services for future
physical-work and recovery probes. The documented process-local limiter is not
silently reinterpreted as a distributed budget or changed in this CI repair.

Next work needs a designated exact-RC artifact/configuration, a production-path
runner and representative workloads, and explicit resolution of replica-budget
and physical-work/recovery gaps before a fresh long soak. Repeating this
preflight for four hours cannot satisfy its deliberately false exact-RC gate.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
command errors 0. CI failure reproduction is complete; production acceptance
remains blocked. This handoff is not integration approval.
