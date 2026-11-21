# #860 repair checkpoint — job 9bb82e70

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`cb8f57b009b7e4c0b7810ccc9bccc4bef1f13f19`, supplied base
`5765efce8c1f1f65c778dce5d30aa542279ab70d`. Initial working tree was clean.
Review inputs: existing `scripts/soak/run_soak.py`, soak profile/evidence,
`tests/test_soak_promotion_gates.py`, production rate limiter, adjacent
pg-learnings/backpressure tests, relevant ADRs and CI gate definitions.
Planned write scope: this checkpoint; `quality/vulture-baseline.json` only if
an actual scan identifies reviewed unbanked identities. No runtime changes
without reproduced evidence. No GitHub mutations or new execution authority.

## Initial results

- Exact requested vulture scan exited 0; output saved to
  `/tmp/auto-860-vulture.log`. No ledger amendment justified by this scan.
- Supplied prior result exists and reports BLOCKED; its claims are not reused
  as current validation.
- The job directory snapshot contains `events.jsonl`, `manifest.json`,
  `prompt.txt`, `state.json`; no `check-*.log` files were present. Driver
  verification logs are therefore unavailable, not assumed green.
- Existing profile explicitly says the host-process harness cannot sign an
  exact-RC soak. Current evidence already retracts the shared-limiter claim.

Assumption: this is the writer/CI-repair lane. A clean gate does not authorize
inventing ledger debt or treating historical short preflight runs as promotion
proof. Further validation and acceptance disposition follow below.

## Executed validation

All commands used this assigned worktree; validation timeouts were 600 seconds
(120 seconds for the evidence evaluator and Docker prerequisite).

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,359 reviewed identities / 1,359 findings; zero unclassified or never-allowlist findings |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 2,770 files already formatted |
| `uv run python scripts/check-ratchet-provenance.py` | PASS: 45 quality JSON consumers have explicit provenance |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs` | 80 passed, 5 skipped; skipped PostgreSQL cases require `MAISTRO_TEST_PG_DSN` |
| `DOCKER_HOST=unix:///var/run/docker.sock timeout 60 docker info` | FAIL (exit 1): cannot connect to Docker daemon; plugin I/O warnings also emitted |
| `uv run python -` importing `failed_promotion_checks` and evaluating the four frozen historical JSON packs | PASS: all four rejected for both duration and exact artifact |

Raw local output: `/tmp/auto-860-{vulture,ruff-check,ruff-format,provenance,surface,pytest,docker,evidence-check}.log`.
The vulture workflow's scan arguments match the executed command. Its default
trusted-base resolution reported `83db0175dd94`; this is not a claim that the
scan used the lane's supplied historical develop base.

The evidence evaluator read only `m3a-soak-evidence.json`,
`m3a-repair-validation.json`, `m3a-round5-final.json`, and
`m3a-round6-shakedown.json` under `docs/testing/soak/evidence/`. Runs 5 and 6
report 90.17 and 90.43 seconds respectively. Both fail `sustain_duration` and
`exact_rc_artifact`. Missing fields in earlier packs fail closed. Existing
regressions execute the real rate-limit middleware: the same identity receives
`[200, 200, 429]` independently on each replica, for authenticated and
unauthenticated cases. ASGI tests are not a live multi-replica RC soak.

## Architecture reconciliation

Read repository instructions and the documentation authority hierarchy, plus
ADR-081 (Proposed deployment guidance), accepted ADR-081226-a66b (canonical
Run/NodeRun/Attempt lifecycle), and accepted ADR-081626-f383 (execution leases
and stale-writer fencing). ADR-081 is not accepted authority. Admission counts
cannot establish physical-work uniqueness; lease expiry alone cannot invent
reclaim authority. No competing scheduler, Goal store, event store or auth path
was added, and no acceptance condition was relaxed.

## Acceptance disposition

| #860 criterion | Current evidence / disposition |
|---|---|
| Representative RC profile | PARTIAL: profile defines HTTP mix and thresholds, but explicitly lacks multi-user/Workspace, fan-out, successful tools/models, Design/Canvas and sustained reconciliation coverage. RC representativeness UNVERIFIED. |
| At least two application replicas | Historical preflight only; current live exact-RC replicas UNVERIFIED because Docker is unavailable. |
| Sustained saturation, growth, reclaim, retries and leaks | UNVERIFIED; no new load run. Regression validates child resource sampling, not long-window stability. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED; admission-only probes and terminal Run counts do not prove physical execution fencing. |
| Rate/security/degraded non-bypass | NOT MET as a cluster-wide allowance: real middleware regression reproduces independent replica budgets. Full RC security/degraded behavior UNVERIFIED. |
| Complete telemetry with explicit thresholds | PARTIAL profile/instrumentation only; application-loop latency and full worker/container census remain gaps. Production observations UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED; historical process rejoin is insufficient for physical Attempt recovery proof. |
| Long-running exact RC artifact/config soak | NOT MET: current evaluator rejects every historical pack; host preflight always fails exact-artifact gate. No new soak attempted without working Docker. |
| Findings filed/reclassified before promotion | Local F-series classifications retained; external filing UNVERIFIED and prohibited in this lane. |
| Machine/human evidence with exact artifact hashes | Historical preflight packs exist; promotion-grade exact image/config evidence UNVERIFIED. |

## Handoff

Verdict: **BLOCKED**, not integration approval. The requested CI debt repair
has no reproduced debt to amend. The substantive blockers are not solved by
another ledger edit or short smoke run: a working deployment environment,
complete RC profile/runner, resolution of the replica-budget contract, and a
new >=14,400-second exact-image/configuration soak with physical-work oracles
are needed. Do not repeat this gate-only lane expecting promotion evidence.

Only this validation checkpoint changed. No tests were added or modified, so
there is no inventory delta. No historical evidence, production code, ledger,
grants or runtime configuration changed. Local commit required; no push.
Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: restore Docker and
complete the exact-RC workload/evidence contract before scheduling the soak}.
