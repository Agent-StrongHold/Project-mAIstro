# #860 repair checkpoint — job a6a77037

## Frozen scope and fresh prerequisite evidence

Only assigned issue #860, branch `auto-860`, starting clean HEAD
`182db4c0ee9467b9f8a4a2f86c6fb7cf6255e486`, supplied base
`5765efce8c1f1f65c778dce5d30aa542279ab70d`. No uncommitted work or merge
conflict to salvage. Previous result read, not accepted as fresh validation.
Job-directory snapshot supplied no `check-*.log` files.

- Explicit CI-repair command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **exit 0**, 1,359 findings match 1,359 reviewed identities; zero unclassified
  or never-allowlist findings. Reported trusted base `83db0175dd94` differs from
  the historical supplied base. No actual debt mismatch to repair; no ledger
  amendment justified.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 60 docker info`: **exit 1**,
  cannot connect to the daemon. Also reports Docker plugin metadata I/O errors.
  Production RC soak is blocked; no load run started.

Command logs are under
`/home/dev/maistro/jobs/a6a7703747944aac84448cd498f87038/`:
`vulture.log`, `docker-info.log`, `prerequisite-results.log`.
Commands used a 1,200-second tool timeout (Docker itself bounded to 60 seconds).

Read repository instructions, profile/evidence, prior checkpoint, workflow and
ADRs. Accepted ADR-081426-1f7c reserves physical execution identity for Attempts;
accepted ADR-081626-f383 does not authorize implicit expiry-based takeover.
Schedule admission uniqueness is not physical-work uniqueness. Accepted ADR-085
specifies per-principal rate limiting, not permission to call process-local
budgets shared. Deployment ADR-081 is Proposed, not overriding authority.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt; no new authority introduced.

## Completed focused validation

Fresh commands, each exit 0 (1,200-second tool timeout):

- `uv run ruff check .`: all checks passed (`ruff-check.log`).
- `uv run ruff format --check .`: 2,770 files already formatted
  (`ruff-format.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped in 2.38s** (`pytest.log`). All five skips require
  `MAISTRO_TEST_PG_DSN`. The schema-fence unit test verifies emitted SQL, not
  concurrent live PostgreSQL boot. Production-stack tests validate configuration
  contracts, not a running Compose deployment.
- `uv run python scripts/check-ratchet-provenance.py`: 45 quality JSON consumers
  classified; delegated gates passed (`provenance.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: complete (`surface.log`).

The vulture and companion commands match
`.github/workflows/vulture-ratchet.yml:77-85`. No new tests or inventory-count
changes; no inventory delta needed. No ledger/grant changes.

An additional `uv run python -` check (600-second timeout, exit 0) imported the
current `failed_promotion_checks` and evaluated the frozen four historical packs:
`m3a-soak-evidence`, `m3a-repair-validation`, `m3a-round5-final`,
`m3a-round6-shakedown`. Every pack fails `sustain_duration` and
`exact_rc_artifact`; runs 5/6 record 90.17/90.43 seconds, not 14,400.
`preflight_artifact_check()['ok']` is false (`evidence-check.log`). This is an
executed evidence evaluation, not a new soak.

## Acceptance audit

| Criterion | Fresh evidence and remaining gap |
|---|---|
| Representative RC profile | PARTIAL: `m3a-load-profile.md:146-162` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background work. Representative production coverage UNVERIFIED. |
| At least two application replicas | Production configuration contracts pass; two running exact-RC replicas UNVERIFIED because Docker is unreachable. |
| Sustained saturation, growth, expiry/reclaim, retries, leaks and shutdown | UNVERIFIED; sampler regression executes a real child allocation, not sustained application traffic. Historical short runs cannot satisfy this criterion. |
| Exactly-once/fenced physical work and reconciliation | UNVERIFIED under production load. HTTP admission-oracle tests reject vacuous all-conflict success; schedule probe admission followed by cancellation does not execute physical Attempts. |
| Concurrent rate/security/degraded non-bypass | Shared allowance NOT MET: `tests/test_soak_promotion_gates.py:431-486` executes real production middleware and observes `[200, 200, 429]` independently on each replica for the same identity. `rate_limit.py:25-30` explicitly documents independent process budgets. Full RC security/degraded load behavior UNVERIFIED. |
| Complete telemetry and pass/fail thresholds | PARTIAL profile/instrumentation only; application event-loop latency, complete worker/container census, saturation and long-window observations UNVERIFIED. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED. Process exit/rejoin and terminal Run counts are not physical-work loss/duplication oracles. No live RC run executed. |
| Long-running exact RC artifact/configuration | NOT MET: current evaluator rejects all four historical packs; `scripts/soak/run_soak.py:635-647` explicitly rejects the host preflight artifact. No new four-hour run. |
| Findings filed/reclassified to earliest invariant | Local F-series classifications reviewed in `m3a-soak-evidence.md`. External filing UNVERIFIED; no GitHub mutations allowed or performed. |
| Machine/human evidence bound to immutable artifact/config hashes | Historical preflight packs present and evaluated; new promotion artifact/configuration proof UNVERIFIED. |

Existing H3 shared-store language has already been retracted at
`m3a-soak-evidence.md:171`. No evidence supports repeating that old repair or
changing runtime behavior speculatively. Passing six local-overload probes is
not proof of one cluster-wide budget; this remains an acceptance mismatch.

## Handoff

**BLOCKED.** Only this checkpoint changed. No code, runtime configuration,
historical evidence, tests, ledger or grants changed. Commit locally; this is
not integration or promotion approval.

Next: restore a working exact-RC deployment environment, finish representative
workloads and physical-work/telemetry oracles, resolve the replica-budget
acceptance mismatch, then run at least 14,400 seconds against the immutable RC
artifact/configuration and publish its evidence. Docker recovery alone is
insufficient. Repeating the already-passing vulture gate cannot complete #860.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC deployment
and workload/evidence prerequisites}. The requested CI-debt check completed;
the issue remains incomplete.
