# Issue #860 — repair checkpoint 1cb3fc64

## Frozen scope and initial state

Assigned writer worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD `4e4e81ed75e0a6dc121b40b1e91e16301c935a30`; supplied base
`15157c6f2bc57d5f7dc7d9e212adb323864d32ef` resolves (initial diff succeeded).
Initial worktree is clean: no incoming edits to salvage or merge conflict.
Only issue #860 is in scope. No GitHub mutations or deployment changes.

Frozen inspection/validation set: supplied issue and prior result, repository
instructions, relevant canonical execution/recovery/security/deployment ADRs,
`m3a-load-profile.md`, `m3a-soak-evidence.md`, the four historical evidence packs
(`m3a-soak-evidence`, `m3a-repair-validation`, `m3a-round5-final`,
`m3a-round6-shakedown`), `scripts/soak/run_soak.py`, rate-limit middleware,
production Compose contract, adjacent promotion/production-stack/PG-learning/
task-backpressure tests, and vulture workflow/gate/ledger. Planned edits: this
checkpoint and only repairs justified by new failed validation.

The supplied job directory snapshot has no `check-*.log` files. Writer validation
will run afresh; previous green checks and Docker failure are not assumed true.
Ambiguity: ledger amendment is requested without failing identities. Run the
exact requested scan and change the ledger only for demonstrated reviewed debt.
No immutable RC image/configuration is supplied: do not invent one or promote
host-process preflight evidence. Prior result is BLOCKED, not a sync conflict.

## Validation and acceptance

Fresh prerequisite checks (1,200-second tool timeout):

- Exact requested vulture scan: exit 0; 1,359 findings match 1,359 reviewed
  identities, zero unclassified/never-allowlist. No ledger amendment justified.
  The gate selected trusted base `83db0175dd94`, not the supplied historical base.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 60 docker info`: exit 1;
  daemon unreachable at the specified socket. No live production soak started.
- Logs: supplied job directory, `vulture.log` and `docker-info.log`.

Architecture reconciliation: accepted ADR-081426-1f7c identifies physical work
by Attempt, so deduplicated Run admission is insufficient. Accepted
ADR-081626-f383 expressly does not authorize implicit lease-expiry takeover.
ADR-085 requires principal-keyed limits but does not establish shared replica
state. ADR-081 is Proposed. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt;
no new execution or authorization authority is warranted by this validation.

Focused checks completed (1,200-second tool timeout), all exit 0:

- `uv run ruff check .`: all checks passed (`ruff-check.log`).
- `uv run ruff format --check .`: 2,770 files formatted (`ruff-format.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped in 2.31s** (`pytest.log`). The five live PostgreSQL
  tests require `MAISTRO_TEST_PG_DSN`; their skipped behavior is not proven.
- `uv run python scripts/check-ratchet-provenance.py`: 45 consumers classified,
  delegated gates passed (`provenance.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: complete (`surface.log`).
- `uv run python -`: imported the current evaluator and asserted all four frozen
  historical packs fail both `sustain_duration` and `exact_rc_artifact`; asserted
  host preflight artifact check is false (`evidence-check.log`). Runs 5/6 record
  90.17/90.43 seconds, not 14,400. Older packs lack the top-level duration value.

Vulture and companion gate arguments match `.github/workflows/vulture-ratchet.yml`.
These results are local validation, not proof against a future integration base.
No code, runtime configuration, ledger/grant, tests or historical evidence changed;
there is no test inventory delta. Only this checkpoint is added.

## Acceptance audit

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | PARTIAL. `m3a-load-profile.md:146-162` acknowledges absent concurrent users/Workspaces, graph fan-out, successful model/tool calls, Design/Canvas and Goal/background reconciliation. Representative production coverage UNVERIFIED. |
| At least two application replicas | Compose contract tests pass, but do not boot replicas. Live exact-RC exercise UNVERIFIED; Docker prerequisite failed. |
| Sustained saturation, growth, reclaim, retry, leak observation | UNVERIFIED. Real child-process sampler regression passes but is not sustained production traffic. |
| Exactly-once/fenced physical work and reconciliation | UNVERIFIED under load. Admission-oracle tests reject vacuous/all-conflict receipts; admission identity is not physical Attempt uniqueness. |
| Rate/security/degraded non-bypass | NOT MET. Executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:431-486`) observes `[200, 200, 429]` independently on both real middleware instances for the same authenticated/unauthenticated identity. Full concurrent production security/degraded behavior UNVERIFIED. |
| Complete telemetry with thresholds | PARTIAL profile/instrumentation only. Application event-loop lag, full worker/container census, saturation and long-window measurements UNVERIFIED. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. Historical process exit/rejoin and terminal Run counts cannot establish physical-work recovery. No live RC run in this round. |
| Long-running exact RC artifact/configuration | NOT MET. Evaluator rejects all four historical packs; `scripts/soak/run_soak.py:635-647` explicitly rejects host preflight as exact-RC evidence. |
| Findings filed/reclassified to earliest invariant | Local F-series findings reviewed in `m3a-soak-evidence.md`; external filing UNVERIFIED. No GitHub mutations permitted or performed. |
| Hash-bound machine/human promotion evidence | Historical preflight packs inspected and rejected, not relabelled. Exact-RC promotion evidence UNVERIFIED. |

Prior H3 contradiction is already corrected in `m3a-soak-evidence.md:171`.
`rate_limit.py:25-30` documents independent replica allowances; six overloaded
paths cannot prove a shared allowance. No cosmetic second repair is warranted.

## Handoff — BLOCKED

The requested exact-debt-ledger check is green; there is no evidenced scanner
repair to make. Docker is unavailable, and no selected immutable RC image/config
was supplied. Even restoring Docker would not make the preflight promotion-ready:
representative workloads, physical-work/telemetry oracles and the replica-budget
acceptance mismatch remain unresolved. Obtain those prerequisites, then run at
least 14,400 seconds against the exact production artifact and publish hash-bound
evidence. Any code/runtime-config change requires a new soak.

Commit this checkpoint locally; it is not integration or promotion approval.
Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: RC environment,
workload/oracle coverage and rate-budget contract resolution}. The error is the
Docker prerequisite failure; focused validation passed. All prior work preserved.
