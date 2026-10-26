# Issue #860 — round 17 validation checkpoint

**BLOCKED; not promotion evidence or integration approval.**

## Scope and reconciliation

Assigned writer worktree `auto-860`, starting HEAD
`43fd7d1acf5bb5f6522f2f91771cfe429bf392ac`; initially clean. Processed only
#860 and the explicitly assigned vulture exact-debt-ledger gate. No remote
mutations, conflict resolution, runtime/configuration edits or historical
evidence replacement. This file is the only change; no tests were added, so
there is no inventory delta.

Read `AGENTS.md`, `CLAUDE.md`, the existing profile, evidence, adjacent tests,
production middleware/router wiring and Compose topology. Read accepted ADRs
081426-1f7c (runtime), 082526-7f02 (Attempt dispatch identity), 082126-f69c
(recurrence), 085 (rate policy), 083026-a91e (absent metrics), and
083126-5e62 (quality authority). Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`: admission uniqueness cannot substitute for physical execution
uniqueness. ADR-085's principal-keyed policy does not establish shared limiter
state; do not reinterpret #860's replica-selection requirement as satisfied.

Assumption: no immutable promotion RC/configuration has been designated in this
assignment. The production Compose file describes itself as a reference artifact
and requires deployment pinning (`deploy/docker-compose.prod.yml:11`). Do not
invent artifact equivalence or run another host preflight as promotion proof.

## Fresh executed validation

Job logs: `/home/dev/maistro/jobs/d33c0d52aef748bfab1f5079bf45762d/`.
No driver `check-*.log` files were present at initial inspection. Prior job
results were inspected but not used as fresh validation.

Commands used 1200–1800-second timeouts:

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite tests/
```

- Vulture: **PASS**, 1402 reviewed identities / 1402 findings, zero unclassified
  and never-allowlist findings. No unbanked identity exists to repair or amend.
- Pytest: **102 passed, 5 skipped in 9.77s** (`repair-pytest.log`). All skips
  require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation is claimed.
- Ruff lint/format: **PASS**, 2624 files formatted. Inventory: **PASS**, 4198
  tests in `tests/` (`repair-gates.log`).
- Inline `uv run python -` imported the current soak evaluator and asserted that
  all four frozen historical documents fail both `sustain_duration` and
  `exact_rc_artifact`: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`. Observed top-level
  durations: absent, absent, 90.17 s, 90.43 s. Asserted current
  `preflight_artifact_check()['ok'] is False` (`repair-evidence.log`). This is
  evaluator execution, not a new soak.

## Acceptance audit

| Criterion | Fresh evidence and remaining disposition |
| --- | --- |
| Representative RC profile | **PARTIAL / UNVERIFIED**: inspected `m3a-load-profile.md`; one credential, missing multi-Workspace/user population, fan-out, successful tools/models, Design/Canvas and sustained Goal/background activity. |
| Two supported application replicas | **UNVERIFIED**: production Compose declares two services; ASGI middleware tests do not run deployed RC replicas. |
| Sustained saturation, queue/reclaim/retry/leak/shutdown observation | **UNVERIFIED**: evaluator rejects all historical durations; live child-process sampler regression is not sustained application load. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED**: task-router test admits canonical Runs but starts no worker; historical single-occurrence schedule admission is not a physical-effect oracle. |
| Rate/security/degraded replica-selection non-bypass | **NOT MET** for aggregate rate allowance: executed `test_replica_selection_has_an_independent_production_allowance` observes `[200,200,429]` separately on both instances for the same principal or client. Middleware is installed at `main.py:478`; its documented process-local scope is `api/rate_limit.py:25-30`. Exact-RC concurrent security/degraded behavior remains **UNVERIFIED**. |
| Complete metrics and explicit thresholds | **PARTIAL / UNVERIFIED**: profile thresholds and real child RSS/descriptor sampling regression exist; DB sampling seam is mocked, five PG tests skipped, no application-loop/worker census or sustained RC series. |
| Active-work replica kill/restart and recovery | **UNVERIFIED**: no new restart run; process exit/rejoin and terminal Run counts alone cannot establish physical Attempt fencing. |
| >=4-hour exact RC/configuration soak | **BLOCKED**: no designated immutable RC/config; host harness rejects equivalence at `scripts/soak/run_soak.py:635`; 90.43 s historical shakedown is below 14400 s. |
| Findings filed/reclassified to earliest invariant | **PARTIAL / UNVERIFIED**: inspected existing F11/F12 M3-A evidence-validity classifications; no new load finding or external filing. GitHub mutations prohibited. |
| Human/machine evidence tied to exact hashes | **PARTIAL / UNVERIFIED**: existing packs preserved and rejected mechanically; no qualifying exact-artifact sustained pack published. |

## Required next action

Release owner must designate the immutable RC/configuration. Owning work must
resolve the aggregate-rate acceptance mismatch and complete representative
production workloads, physical-effect/fencing oracles, and required metrics.
Then execute and publish >=4 hours on that exact topology; code/runtime-config
changes require a new soak. Repeating a ledger-only repair cannot provide it.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and
production-path sustained evidence}`. Assigned gate validation is complete;
issue acceptance is not. This documentation-only checkpoint is committed locally.
