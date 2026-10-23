# Issue #860 CI repair checkpoint

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head `f5ad796893276fd0f4ae8bc41d869ede03964793`, supplied base `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Review existing `scripts/soak/`, `tests/test_soak_promotion_gates.py`, associated soak evidence/docs, repository instructions and relevant ADRs.
- Run the exact vulture gate; edit `quality/vulture-baseline.json` only for reproduced and reviewed retained identities, as explicitly authorized by this CI-repair assignment. No grants or gate weakening.
- This handoff records validation and unresolved acceptance. No new production execution authority or scheduler.

## Initial evidence / assumptions

Assigned head resolves and worktree starts clean. Current job directory has no `check-*.log`; inspect supplied prior job `98a11313167b41a98a420abfda80c292/check-3.log` instead and rerun checks. Prior job verdict BLOCKED is a claim to recheck, not acceptance evidence. Role is writer (explicit assigned repair). No remote mutation or integration approval.

## Reproduced results

- Exact vulture command passed: 1322 findings / 1322 reviewed identities, zero unclassified or never_allowlist; trusted base `ab8b3737fa64`. No supported ledger amendment exists.
- Supplied historical check-3 failure is a schema test expecting 21 DDL statements but receiving 24, not a vulture failure. Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **110 passed, 6 skipped** (2.33 s). The historical failure does not reproduce.
- Frozen issue body has ten acceptance criteria. Current load profile explicitly identifies representative-workload and exact-artifact gaps; no immutable promotion image/configuration is designated by the assignment. Do not invent an RC or relabel a host-process preflight as promotion evidence.

## Additional validation

All commands ran in the assigned worktree with a 1000-second timeout:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- `uv run pytest packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`: PASS, 20 tests.
- `uv run python` imported the current soak evaluator and evaluated `docs/testing/soak/evidence/m3a-round30-shakedown.json`: asserted exactly `sustain_duration` and `exact_rc_artifact` fail. Observed 420.08 seconds against 14400 minimum; current `preflight_artifact_check()['ok']` is false. This reevaluates historical evidence; it is not a fresh soak.
- `git diff --check`: PASS before final report update.

The exact vulture invocation was `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, matching `.github/workflows/quality.yml:1079`. No ledger/grant edits or new tests: no inventory delta is necessary. Existing production-seam regressions supply meaningful local checks, not production acceptance.

## Architecture reconciliation

Read repository instructions, documentation authority map, accepted ADR-085, ADR-081626-f383 and ADR-082526-b36a. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. The later renewal ADR supplies expiry/reclaim semantics left open by the original lease ADR; restarting a process is not proof of recovery, nor is unique admission proof of unique physical execution. ADR-085's principal keying does not justify treating independent replica allowances as a shared budget. No new authority, authorization path, or scheduler is introduced.

## Acceptance assessment

| # | Criterion | Fresh evidence / limitation |
|---|---|---|
| 1 | Representative RC workload | UNVERIFIED. Read `docs/testing/soak/m3a-load-profile.md`: current preflight lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background reconciliation. |
| 2 | At least two production replicas | UNVERIFIED. Two-instance ASGI middleware tests passed; no exact-RC deployment executed. |
| 3 | Sustained saturation/reclaim/leak observations | UNVERIFIED. Current evaluator rejects historical 420.08 s against the profile's 14400 s minimum. No new sustained run. |
| 4 | No duplicated physical work | UNVERIFIED. Fencing tests pass, but `scripts/soak/run_soak.py:1070` explicitly says the schedule probe never executes its admitted Run. No multi-replica physical-work observation. |
| 5 | Replica-independent rate/security/degraded enforcement | UNVERIFIED overall, with contrary rate evidence: executed `tests/test_soak_promotion_gates.py:439` observes independent `[200,200,429]` allowances for both authenticated and unauthenticated identities. `api/rate_limit.py:95` constructs the local limiter; production `main.py:648` installs it. |
| 6 | Complete telemetry and thresholds | UNVERIFIED at promotion grade. Profile explicitly distinguishes driver-loop lag from application-loop lag and identifies pool/worker/lease/long-window gaps. No new production telemetry. |
| 7 | Active-work kill/restart/drain/fencing/recovery | UNVERIFIED. Local recovery tests passed; no production Attempt interrupted or recovered in this round. |
| 8 | Long exact-RC soak, repeated after changes | BLOCKED / UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly rejects host-preflight artifact equivalence. Executed promotion tests and historical evaluation confirm fail-closed behavior. No immutable promotion RC/configuration was designated or exercised. |
| 9 | Findings classified before promotion | UNVERIFIED for completeness without representative load. Backlog consistency passes; no GitHub mutations performed or permitted. |
| 10 | Human/machine evidence tied to promoted hashes | UNVERIFIED for RC. Historical machine evidence fails artifact/duration gates; this source-head-bound report is not a promotion evidence pack. |

## Handoff / residual risk

Only this report changes. The historical schema failure and alleged vulture debt do not reproduce, so changing runtime code, tests, or an already-exact ledger would be unsupported. The outstanding block is actual promotion evidence, not a develop-sync conflict. No merge or remote refresh is warranted.

Next owner needs a designated immutable promotion image/configuration, justified representative workload, deployment-level resolution of the replica allowance gap, complete telemetry and active-work fault injection, then a fresh long exact-RC soak with hash-bound evidence and findings disposition. Extending the existing host-process preflight cannot satisfy artifact identity. No acceptance criterion is waived.

Progress: checked 1 assigned issue; done 0 (acceptance incomplete); skipped 0; errors 0 in fresh validation. Verdict BLOCKED. Commit this report locally as a handoff, not integration approval.
