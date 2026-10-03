# Issue #860 — CI repair, job 13ec34d7

## Frozen scope

- Sole item: issue #860, branch `auto-860`.
- Starting HEAD: `027d239cc14dc6e1db7d987fad360ec272426e52`.
- Assigned base: `83db0175dd9465727691d9429c36c4b4c597f2a7`.
- Initial worktree clean; no incoming edits to salvage.
- Review inputs: repository instructions; relevant execution, deployment, rate,
  and evidence ADRs; `scripts/soak/run_soak.py`; its adjacent promotion tests;
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md` and existing
  evidence packs; production rate limiter; prior job result.
- Edit scope: this report and, only if actual required scanner evidence warrants
  it, reviewed source identities and `quality/vulture-baseline.json`.
- Driver logs: job directory has no `check-*.log` files. Prior claims are not
  treated as current validation.
- Assumption: this is the assigned writer/CI-repair round, not a read-only
  verifier round. No deployment artifact or production configuration is inferred.

## Progress

- Required exact vulture gate PASS: 1359 reviewed identities / 1359 findings;
  zero unclassified, zero never-allowlist. No source or ledger amendment justified.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info` FAIL (exit 1): daemon
  unreachable. Live Compose validation is blocked in this cell.
- Historical H3 shared-store wording is already repaired: the current evidence
  document explicitly reports independent replica budgets. No cosmetic repair.
- ADR review: accepted lifecycle/fencing ADRs preserve canonical execution;
  ADR-082526-b36a adds renewal/reclaim to the earlier fencing contract. Do not
  mistake the older ADR's deferred reclaim boundary for current behavior.
  ADR-081 deployment is Proposed; ADR-085 requires per-principal rate limiting
  but does not prove a cluster budget. ADR-083026-a91e forbids presenting absent
  measurements as zero. No new execution or authorization authority introduced.
- Focused tests, static gates and historical-pack rejection checks completed below.

## Executed validation

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1359/1359 reviewed identities; no new debt |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2770 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped in 2.29s; skips require `MAISTRO_TEST_PG_DSN` |
| `uv run python scripts/check-deployment-claims.py` | PASS; component-existence check, not a live deployment |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified/discovered lifecycles |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAIL, daemon unreachable |

An inline `uv run python` probe loaded `scripts/soak/run_soak.py` using `runpy`
and asserted `sustain_duration` and `exact_rc_artifact` occur in
`failed_promotion_checks` for each frozen historical pack:
`m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`,
and `m3a-round6-shakedown.json`. All assertions passed. The last two report
90.17 and 90.43 seconds. No raw evidence was changed.

The executed replica-selection regression instantiates the production middleware
for both authenticated and unauthenticated identities. Exhausting replica 1 gives
`[200, 200, 429]`; the same identity then gets `[200, 200, 429]` from replica 2.
This disproves a shared budget, not per-replica enforcement. ASGI instances are
not a live production topology. The task-router regression exercises real Run
admission/backpressure and recovery when a slot frees. The schema-fence test
checks SQL ordering using a fake connection, not concurrent PostgreSQL startup.
The sampler regression uses a real child process, not a long-running soak.

## Acceptance audit

| Issue criterion | Current evidence / disposition |
| --- | --- |
| Representative release-candidate profile | PARTIAL: `m3a-load-profile.md` defines mix/thresholds but explicitly lacks concurrent Workspaces/users, fan-out, successful tools/models, Design/Canvas and Goal/background-worker workload justification. RC representativeness UNVERIFIED. |
| At least two application replicas | Boot-contract tests pass for configuration; live exact-RC execution UNVERIFIED. |
| Sustained saturation, growth, expiry/reclaim, retries and leaks | UNVERIFIED: all four historical packs rejected by executed duration gate; no new live load. |
| No duplicate physical work, schedule/task/Run/Attempt and Goal reconciliation | UNVERIFIED: admission probe cancels its queued Run; it cannot prove physical execution uniqueness or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared allowance: executed production middleware regression shows independent budgets. Sustained security/degraded behavior UNVERIFIED. |
| Complete telemetry and thresholds | PARTIAL: documented thresholds and sampler regressions; production application-loop, worker, PostgreSQL/pool/lock, queue, error/timeout and leak observations UNVERIFIED. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED: historical process exit/rejoin does not correlate physical Attempts or prove no loss/duplication. |
| Long-running exact RC artifact/configuration; re-soak after changes | NOT MET: no selected immutable RC artifact/config supplied, Docker unavailable, all four packs rejected. `run_soak.py:635-646` explicitly rejects host preflight. |
| Load findings filed/reclassified at earliest milestone | PARTIAL: local F1-F12 records include attribution; external filing UNVERIFIED. No GitHub mutation permitted or performed. |
| Human/machine evidence with exact hashes | PARTIAL: historical packs exist; promotion-eligible image/package/commit/config-bound evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not promotion or integration approval. Changed file: this report only.
No source, runtime configuration, gate, ledger, inventory, or historical evidence
was edited. No tests added, so no inventory delta is required. A green ledger
scan supplies no evidence-based identity repair to make.

Next: provide a working Docker cell and the selected immutable RC images,
normalized configuration and provider setup; complete missing representative
production workloads, physical-work recovery oracles and telemetry; resolve the
replica-budget acceptance mismatch; execute a >=14400-second soak of the frozen
RC. Any code/runtime-config change requires another soak. Preserve canonical
Goal -> Graph -> Run -> NodeRun -> Attempt authority, including store-owned fencing.

Progress: checked 1, done 0, skipped 0, errors 1 (Docker prerequisite).
CI-ledger assessment complete; acceptance remains blocked. This report is the
local committed checkpoint. No push, GitHub mutation or destructive git command.

