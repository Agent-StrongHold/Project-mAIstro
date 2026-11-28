# Issue #860 repair checkpoint

Frozen scope: issue #860 only, branch `auto-860`, starting head
`c0d5410addd892f0dbc129fb6c6a71273f15ff17`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. No GitHub mutations.

Initial inspection: assigned worktree clean; head matches. Supplied prior result
(`2ed8bf3dfedc43dd97730cb99a012da8/result.json`) reports BLOCKED with production
soak criteria unverified. Current job directory has no `check-*.log` files.

Assumption: this is a writer repair round, specifically authorized to review
vulture identities and amend that ledger; local tests cannot establish deployed
multi-replica or exact-release-candidate soak acceptance. Inspect the supplied
context and existing architecture before making any implementation changes.

The exact requested vulture scan passes: 1,322 findings, 1,322 reviewed
identities, zero unclassified or never-allowlist findings. No ledger amendment
is warranted. Prior check-3.log shows a 24-versus-21 schema-fence assertion;
current test already lists all 24 statements. Fresh execution passes below.

Inspection scope is frozen to the existing soak profile/runner/promotion tests,
the learnings schema fence, production rate/task seams, accepted execution and
fencing ADRs, CI gate configuration, and this round's report. No other issues
or historical reports will be processed.

## Executed validation

All commands used 1,200-second timeouts except the initial vulture scan (1,000).

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,322 reviewed identities/findings.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. Prior schema failure does not reproduce.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 73 passed.
- `uv run pytest packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`: 20 passed.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

## Architecture reconciliation

Read repository instructions, documentation authority map, accepted execution
runtime ADR-081426-1f7c, fencing ADR-081626-f383 and later accepted reclamation
ADR-082526-b36a. The prior report's implication that reclaim still lacks a
contract is outdated: ADR-082526-b36a defines fenced renewal, optional TTL,
CANCELLED reclamation, executor heartbeat and canonical recovery wiring.
A production soak must exercise that existing authority, not invent takeover
semantics or a competing scheduler. Preserve Goal -> Graph -> Run -> NodeRun
-> Attempt. Passing unit tests do not prove physical-work uniqueness under
process loss.

## Acceptance assessment

| Criterion | Fresh evidence / disposition |
|---|---|
| Representative RC profile | UNVERIFIED. Read `m3a-load-profile.md`, whose remaining-gaps section explicitly lacks concurrent users/Workspaces, fan-out, successful tool/model, Design/Canvas and Goal workloads; no selected-RC applicability assessment supplied. |
| Two deployed application replicas | UNVERIFIED. Two-instance ASGI probes executed; no deployed replica experiment this round. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. No sustained production run. The existing optional-TTL contract is the reclamation authority. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | UNVERIFIED. Twenty fencing/recovery unit tests pass, not a cross-process physical-work experiment. |
| Replica-resistant security/degraded behavior | UNVERIFIED overall; `tests/test_soak_promotion_gates.py:439` freshly reproduces independent `[200,200,429]` allowances on both replicas for one identity. `main.py:648` installs the production middleware; `api/rate_limit.py:32` documents N-times aggregate allowance. This does not establish a deployed ingress bypass. |
| Production telemetry and explicit thresholds | UNVERIFIED. Profile thresholds exist, but no fresh PostgreSQL/application-loop/worker/resource/queue/error series. Driver-loop sampling is not application-loop telemetry. |
| Active-work kill/restart, drain and recovery | UNVERIFIED. Unit tests are insufficient; `tests/test_soak_promotion_gates.py:564` reproduces receipt 200 locally and 404 on peer through the production router (`api/tasks.py:144` reads the local queue). |
| Long exact-RC soak | UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly rejects exact-artifact equivalence. Executed CLI regression tests reject synthetic four-hour preflight evidence. No immutable RC image/effective configuration designated in the assignment. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog gate passes; no fresh load experiment or complete classification audit. GitHub mutation prohibited. |
| Hash-bound machine/human production evidence | UNVERIFIED. This report identifies local HEAD and checks only; historical soaks do not establish current-RC acceptance. |

## Disposition

BLOCKED. The requested vulture failure and historical schema failure do not
reproduce; no actual evidence warrants changing production code, tests or the
ledger. The exact scan matches `.github/workflows/vulture-ratchet.yml:82-85`.
No tests added, so no inventory delta is required. Only this round's report
changes; the pre-existing checkpoint remains byte-for-byte intact.

Next: designate immutable RC artifacts and effective configuration, resolve the
representative traffic and replica-budget/receipt constraints, and execute a
production-artifact soak of at least four hours with active-work crash/drain,
canonical TTL renewal/reclaim, stale-writer and physical-effect observations.
Capture the required production telemetry and artifact/configuration hashes.
Do not repeat passing lint/schema scans as a substitute for that evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; errors 0
validation commands. Local commit is a blocked handoff, not integration approval.

