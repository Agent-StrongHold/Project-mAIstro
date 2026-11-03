# Issue #860 — repair checkpoint (job c56edba3)

## Frozen scope and initial state

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`. Starting HEAD verified: `737caad1aa65e4b0c2ba37ac77d90da4f9961ad4`;
assigned base: `83db0175dd9465727691d9429c36c4b4c597f2a7`. Worktree initially clean.
No incoming diff to salvage. No GitHub mutations or integration actions permitted.

Review snapshot: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`tests/test_prod_stack_boot_contract.py`, the changed pg_learnings and tasks modules
and their adjacent tests, production rate limiter and Compose configuration,
`docs/testing/soak/{m3a-load-profile,m3a-soak-evidence}.md`, the four historical
JSON evidence packs, and relevant lifecycle/deployment/fencing ADRs.
Write scope: this checkpoint; evidence-based code/test repairs if demonstrated;
`quality/vulture-baseline.json` only for actual reviewed findings from the assigned
exact-debt-ledger gate. No speculative ledger amendments.

The job directory snapshot contains no `check-*.log` files. Driver verification
is unavailable, not assumed green. Prior job result and handoff read as historical
context only. Writer assignment takes precedence over generic verifier wording.
No exact RC image digest/configuration is supplied; do not invent one or claim
host-process preflight equals production Compose.

## Results

- Required exact vulture command PASS: 1359 reviewed identities / 1359 findings,
  zero unclassified and zero never-allowlist findings. No ledger change justified.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info` FAIL: daemon unreachable.
  No production Compose soak can run in the current cell.
- Architecture reviewed: ADR-081 is Proposed; accepted ADR-081226-a66b and
  ADR-081626-f383 retain the canonical lifecycle and store-owned fencing.
  Accepted ADR-082526-b36a adds TTL renewal/reclamation to that contract. Unlike
  the prior handoff's reading of the older ADR alone, reclaim is now defined;
  its existence is not evidence of a successful multi-replica soak. No parallel
  scheduler/reclaim/authorization authority will be introduced.

## Executed focused validation

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1359 identities, no debt changes needed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2770 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped (all require `MAISTRO_TEST_PG_DSN`) |
| `uv run python scripts/check-deployment-claims.py` | PASS, component-existence check, not live deployment |
| `uv run python scripts/check-execution-lifecycles.py` | PASS, 19 classified lifecycles |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAIL, daemon unavailable |

An executed inline `uv run python` probe loaded the existing driver with `runpy`
and asserted that `failed_promotion_checks` rejects both `sustain_duration` and
`exact_rc_artifact` for each frozen historical pack: `m3a-soak-evidence.json`,
`m3a-repair-validation.json`, `m3a-round5-final.json`, and
`m3a-round6-shakedown.json`. All assertions passed; last two windows are 90.17
and 90.43 seconds, not 14400. No historical evidence rewritten.

Existing regressions exercise the actual task router/Run admission ceiling (429
with Retry-After, isolation and recovery after a slot frees), DDL lock ordering,
the host sampler's real child process, and production limiter middleware. The
DDL test uses a fake connection: this validation does not establish concurrent
PostgreSQL boot correctness. Boot-contract tests inspect configuration and
startup validation, not running containers.

The production-middleware replica-selection regression passed for authenticated
and unauthenticated identities: each instance independently returns
`[200, 200, 429]` to the same identity. This falsifies cluster-wide non-bypass,
not local enforcement. The prior H3 shared-store quotation is stale:
`m3a-soak-evidence.md:171` already disclaims that claim. No cosmetic re-repair
of that text is warranted.

## Acceptance audit

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload | PARTIAL: profile read; concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads explicitly missing. RC applicability UNVERIFIED. |
| Two application replicas | Compose declares both; boot-contract tests pass. Live exact-RC multi-replica behavior UNVERIFIED. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED: historical packs fail the executed duration gate; subprocess sampling test is not a soak. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED: historical schedule probe admits then cancels one Run; admission uniqueness cannot establish execution uniqueness. Canonical lease/reclaim contracts exist but were not soaked here. |
| Rate/security/degraded behavior, non-bypass | Non-bypass NOT MET by the executed production-middleware regression; long-window security/degraded behavior UNVERIFIED. |
| Full telemetry with explicit thresholds | PARTIAL: thresholds documented; application-loop, workers, production pool/lock/queue/error measurements UNVERIFIED. |
| Kill/restart during active work with fencing/recovery | UNVERIFIED: old exit/rejoin observations do not correlate physical Attempts or prove no loss/duplication. |
| Long-running exact RC and re-soak on change | NOT MET: four packs rejected; `run_soak.py:635-645` always rejects host preflight as exact RC. No selected immutable RC artifact supplied. |
| Load findings filed/reclassified | PARTIAL: local F1-F12 findings inspected, including milestone attribution; external filing UNVERIFIED and prohibited in this lane. |
| Machine/human hash-bound evidence | PARTIAL: historical packs exist; promotion-eligible artifact/config evidence UNVERIFIED. |

## Handoff

**BLOCKED.** Only this checkpoint changed; no production, tests, gates, ledgers,
configuration or historical evidence changed. Existing meaningful tests were run;
no new test collection means no inventory delta is required. No substantive
repair is justified by the green exact-ledger check, and a short emulator rerun
would not resolve the acceptance failures.

Next requires an operator-provided working Docker cell and selected RC image /
normalized configuration / provider setup; completion of representative Compose
workloads, physical-work recovery oracles and missing telemetry; resolution of
the replica-budget acceptance mismatch; then a >=4-hour soak of that frozen RC.
Any runtime/configuration change requires a new soak. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt authority throughout.

Checkpoint: checked 1 issue, done 0, skipped 0, errors 1 (Docker prerequisite).
CI-ledger repair assessment completed with zero unbanked identities. Progress is
committed locally as a blocked handoff, not an integration approval. No push,
GitHub mutation, branch deletion or destructive git operation performed.
