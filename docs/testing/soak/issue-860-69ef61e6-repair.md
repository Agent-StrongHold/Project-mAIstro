# Issue #860 — repair checkpoint 69ef61e6

## Frozen scope

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`. Starting HEAD `2acd44514c450a372c4a34890cab4111c78d176f` resolves
and worktree is clean; supplied base `5765efce8c1f1f65c778dce5d30aa542279ab70d`
resolves. No salvage or merge-conflict recovery required.

Snapshot: issue acceptance and prior result supplied by the lane; existing
`m3a-load-profile.md`, `m3a-soak-evidence.md`, four historical JSON packs
(`m3a-soak-evidence`, `m3a-repair-validation`, `m3a-round5-final`,
`m3a-round6-shakedown`), `scripts/soak/run_soak.py`, adjacent promotion,
production-stack, PostgreSQL learning-store and task-backpressure tests,
rate-limit middleware, relevant execution/recovery/security/deployment ADRs,
and vulture CI workflow/ledger. Planned edit scope: this checkpoint plus only
repairs justified by fresh failing checks. No prior success is fresh evidence.

The supplied job directory contains no `check-*.log` files in the initial
snapshot. This is a writer round; execute validation locally instead.
Previous round reported an unreachable Docker daemon, a green vulture gate,
and unmet exact-RC soak acceptance. These claims require fresh checks.

Ambiguity: the lane calls for ledger amendment, but no failing identities are
supplied. Run the exact requested scan first; amend only actual reviewed debt,
not the ledger cosmetically. Exact-RC deployment identity is not supplied;
do not invent a promotable artifact or substitute a host preflight.

## Validation

Fresh prerequisites (1,200-second tool timeout):

- Requested vulture command: exit 0, 1,359 findings match 1,359 reviewed
  identities; zero unclassified/never-allowlist findings. No ledger repair
  justified. Gate resolved trusted base `83db0175dd94`, not the historical
  supplied base; this is not proof against a future integration target.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 60 docker info`: exit 1,
  cannot connect to daemon. Also reports plugin metadata I/O errors.
  No production soak started; environment prerequisite remains blocked.
- Logs: supplied job directory, `vulture.log`, `docker-info.log`.

Architecture reconciliation: accepted ADR-081426-1f7c identifies physical work
by Attempt, not Run. ADR-081626-f383 does not authorize implicit lease-expiry
takeover. ADR-085 calls for per-principal limits; it does not establish shared
replica state. Deployment ADR-081 is Proposed. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt authority; admission counts alone
cannot establish physical-work uniqueness or recovery.

Focused validation completed, all commands exit 0 (1,200-second tool timeout):

- `uv run ruff check .`: all checks passed (`ruff-check.log`).
- `uv run ruff format --check .`: 2,770 files formatted (`ruff-format.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped in 3.33s** (`pytest.log`). All skips require
  `MAISTRO_TEST_PG_DSN`. SQL-emission assertions do not prove live concurrent
  database boot; Compose contract tests do not start production containers.
- `uv run python scripts/check-ratchet-provenance.py`: 45 consumers classified,
  delegated gates passed (`provenance.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: complete (`surface.log`).
- `uv run python -`: imported the current soak evaluator and asserted rejection
  of all four frozen historical packs for both `sustain_duration` and
  `exact_rc_artifact`; also asserted the host preflight artifact check is false
  (`evidence-check.log`). Runs 5/6 report 90.17/90.43 seconds, not 14,400.

The vulture/companion commands match `.github/workflows/vulture-ratchet.yml`.
No tests added or changed; no inventory delta required. No ledger/grant,
production code, runtime configuration or historical evidence edits.

## Acceptance audit

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | PARTIAL: `m3a-load-profile.md:146-162` explicitly lacks multiple users/Workspaces, fan-out, successful provider/tool work, Design/Canvas and Goal/background reconciliation. Representative production coverage UNVERIFIED. |
| At least two application replicas | Configuration contracts pass; live exact-RC replicas UNVERIFIED because Docker prerequisite fails. |
| Sustained saturation/growth/reclaim/retries/leaks | UNVERIFIED. Real child-process sampler regression passes but is not sustained application traffic. |
| Exactly-once/fenced physical work and reconciliation | UNVERIFIED under load. Admission-oracle regressions reject all-conflict/empty receipts, but one Run per occurrence is not one physical Attempt. |
| Rate/security/degraded non-bypass | Shared-budget claim falsified by real production middleware: `tests/test_soak_promotion_gates.py:431-486` observes `[200, 200, 429]` independently on both replicas for the same identity, authenticated and unauthenticated. Full production concurrency/security criterion NOT MET. |
| Telemetry and explicit thresholds | PARTIAL instrumentation/profile; application-loop latency, complete worker/container census, saturation and long-window observations UNVERIFIED. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED; no live RC run. Historical process exit/rejoin and terminal Run counts do not establish physical-work safety. |
| Long-running exact RC artifact/configuration | NOT MET: fresh evaluator rejects all four packs; host runner explicitly fails artifact identity at `scripts/soak/run_soak.py:635-647`. |
| Findings filed/reclassified to earliest invariant | Local F-series records reviewed in `m3a-soak-evidence.md`; external filing UNVERIFIED. No GitHub mutations permitted or performed. |
| Hash-bound machine/human promotion evidence | Historical preflight packs evaluated, not relabelled. Exact-RC promotion evidence UNVERIFIED. |

The prior H3 contradiction has already been corrected at
`m3a-soak-evidence.md:171`. No second cosmetic repair is justified. Production
middleware explicitly documents independent budgets at `rate_limit.py:25-30`;
six overloaded paths do not prove a shared cluster allowance.

## Handoff — BLOCKED

Only this checkpoint changed. Commit locally; this is not promotion approval.
The requested debt scan is complete with no mismatch. The issue cannot be
completed by repeating green static checks or lengthening the host emulator.

Next: provide a working production deployment environment and selected immutable
RC image/configuration, complete representative workloads and physical-work/
telemetry oracles, resolve the replica-budget acceptance mismatch, then execute
at least 14,400 seconds and publish hash-bound evidence. Docker recovery alone
is insufficient. No new scheduler, execution authority or authorization path
was introduced.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC environment
and workload/evidence prerequisites}. Error is the failed Docker prerequisite;
all focused code checks passed. Prior work preserved.
