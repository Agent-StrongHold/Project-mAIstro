# #860 repair checkpoint — job e74cc9f3

## Scope and reproduced prerequisite results

Single assigned item: #860; branch `auto-860`, initial clean HEAD
`e16f936791a5ec55b453ea1209ef5a9d7128e6e0`, supplied base
`5765efce8c1f1f65c778dce5d30aa542279ab70d`. No sync conflict or uncommitted
work to salvage. No driver `check-*.log` files were present in the job-directory
snapshot. Previous BLOCKED report read, not treated as current validation.

Frozen write scope: this checkpoint, and the vulture ledger only for reproduced,
reviewed debt. No speculative runtime changes or evidence relabeling.

Fresh commands (1,200-second tool timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **exit 0**, 1,359 findings matching 1,359 reviewed identities, zero unclassified/never-allowlist. Default trusted base is `83db0175dd94`, not the supplied historical base. No ledger amendment warranted.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 60 docker info`: **exit 1**, cannot connect to the daemon. Plugin metadata I/O warnings also present. No exact-RC soak started.

Logs: `/home/dev/maistro/jobs/e74cc9f372a5452fab6dccd244ded0d1/{vulture,docker-info}.log`.

Read the profile, evidence pack, prior checkpoint, promotion regression tests,
accepted ADR-081626-f383 (execution fencing), accepted ADR-085 (per-principal
rate limiting), and proposed ADR-081 (deployment). A lifecycle ADR filename
attempt did not resolve; not found, skipped. Reconciliation: a schedule admission
race is not physical Attempt uniqueness; lease expiry alone does not grant
reclaim authority. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. ADR-085
does not justify interpreting process-local budgets as a shared replica budget.
ADR-081 is proposed, not accepted authority.

## Validation and acceptance

Fresh focused validation (1,200-second tool timeout), all exit 0:

- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 2,770 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped in 2.22s**. All skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL claim follows from these tests.
- `uv run python scripts/check-ratchet-provenance.py`: 45 quality JSON consumers classified; delegated checks passed.
- `uv run python scripts/check-shipped-surface-truth.py`: complete.

The vulture command and companion gates match
`.github/workflows/vulture-ratchet.yml:77-85`. Logs are in the supplied job
directory: `ruff-check.log`, `ruff-format.log`, `pytest.log`, `provenance.log`,
`surface.log`.

An additional `uv run python -` check (600-second timeout, exit 0) imported the
current `failed_promotion_checks` and asserted `sustain_duration` and
`exact_rc_artifact` failures on the frozen four historical JSON packs:
`m3a-soak-evidence`, `m3a-repair-validation`, `m3a-round5-final`,
`m3a-round6-shakedown`. Runs 5/6 record 90.17/90.43 seconds, not 14,400.
The host-preflight artifact check also returns false. Log: `evidence-check.log`.
This evaluates historical evidence; it is not a new load run.

| Acceptance | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | PARTIAL: profile read; one-key provider-less mix explicitly lacks concurrent users/Workspaces, fan-out, successful tool/model work, Design/Canvas and sustained Goal reconciliation. Representativeness UNVERIFIED. |
| Two application replicas | UNVERIFIED for current RC; Docker prerequisite failed. Historical host-process evidence is not exact-artifact proof. |
| Sustained saturation, growth, reclaim, retries and leaks | UNVERIFIED. Live child-process sampler regression passes, not a long-running application soak. |
| Exactly-once/fenced physical work, admission, reconciliation | UNVERIFIED under production load. Admission oracle tests pass; one cancelled schedule-probe Run cannot prove physical Attempt uniqueness/recovery. |
| Rate/security/degraded non-bypass | Shared-budget guarantee NOT MET: executed production-middleware tests give the same identity `[200, 200, 429]` independently on both replicas. Full concurrent RC security/degraded behavior UNVERIFIED. |
| Full telemetry with thresholds | PARTIAL profile/instrumentation only; application event-loop latency, worker/container census and long-window observations UNVERIFIED. |
| Active-work kill/restart and drain/fencing/recovery | UNVERIFIED. No live RC deployment; process exit/rejoin or terminal Run counts alone are insufficient. |
| Long-running exact RC artifact/configuration | NOT MET: all four historical packs rejected by current evaluator; host preflight always fails artifact identity. |
| Findings filed/reclassified before promotion | Local F-series classifications reviewed. External filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human hash-bound promotion evidence | Historical preflight packs exist; immutable image/configuration promotion evidence UNVERIFIED. |

The previous H3 shared-store assertion is already retracted at
`m3a-soak-evidence.md:171`; there is no remaining repair to that sentence.
`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30` explicitly
states independent process budgets. Do not introduce a competing authority or
waive the non-bypass criterion to make this issue green.

## Handoff

**BLOCKED.** Only this checkpoint changed; no code, runtime configuration,
historical evidence, tests, ledger or grants changed. No inventory delta needed.
No GitHub actions. Commit this checkpoint locally; it is not promotion approval.

Next: restore a working exact-RC deployment environment, complete the
representative workload and physical-work/telemetry oracles, resolve the
replica-budget acceptance mismatch, then execute at least 14,400 seconds on the
immutable RC artifact/configuration. Docker recovery alone is insufficient.
Repeating a passing debt-repair gate cannot meet these release requirements.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC deployment
and workload/evidence prerequisites}. The requested CI-debt validation completed;
the issue remains incomplete.
