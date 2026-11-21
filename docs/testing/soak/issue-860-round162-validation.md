# Issue #860 — round 162 validation and CI repair

## Scope and state

Processed only issue #860 in `auto-860`. Starting HEAD was
`49a22c6f9d723f186ca828949a9095e51aebf471`; the tree carried two untracked
scratch files from a prior attempt (`make_soak_changes.py`,
`scripts/soak/run_soak.py.backup`) proposing a `--relax-promo-gates` CLI flag
that would hard-code the exact-RC preflight gate to `ok: true`. That approach
was **rejected**: `preflight_artifact_check` is fail-closed by documented
design ("deliberately no CLI override"), and defeating it would fabricate the
one thing issue #860 exists to produce. Both files were preserved byte-exact
outside the tree (job directory `salvage/`, sha256 recorded in the job log)
and removed from the worktree because they also broke repo-wide `ruff check`.

## What this round changed

1. **Develop sync.** `origin/develop` had moved 5 commits past the merge base
   (`ebb5dc03` → `e12e1128`); merged cleanly, no conflicts
   (`464cea2cd Merge remote-tracking branch 'origin/develop' into auto-860`).
   The PR's recorded `mergeable_state` was `behind`.
2. **DevSkim: run_soak.py alerts triaged at the finding sites.** The PR-head
   scan (analysis 2022202231, `refs/pull/1672/merge`) carried 16 alerts on
   `scripts/soak/run_soak.py`: 15 × DS162092 ("Accessing localhost…") on the
   harness's by-design `127.0.0.1` literals and 1 × DS148264 on the seeded
   `random.Random(worker_id)` that keeps the request mix reproducible. Each
   now carries the repo's standard inline suppression with reason and expiry
   (same pattern as `packages/hive-conductor/backend/stores.py:523` and
   `packages/maistro-core/src/maistro/capabilities/provider_adapters.py:899`).
   No behavior changed; the loopback topology and the deterministic mix are
   load-bearing harness properties.
3. **DevSkim: evidence-corpus alerts NOT triaged here — governance needed.**
   ~255 of the 271 PR-new alerts are on `docs/testing/soak/evidence/*.json`:
   DS173237 fires on the commit SHAs the evidence is contractually required to
   record (issue AC: "tied to exact image/package/commit/config hashes") and
   DS162092 on the loopback origins actually used. JSON cannot carry inline
   suppressions, rewriting recorded evidence would falsify it, and editing
   `devskim.yml` scan scope is a security-governed decision (each prior scope
   change — `**/static/swagger-ui/**` #1425, `**/benchmarks/corpora/**`,
   `**/maistro_design/systems/catalog/**` — landed as a reviewed scope commit,
   and `tests/test_devskim_scan_scope.py` guards the glob contract). The
   precedent-backed remedy is one scoped location glob for the generated
   evidence corpus; it belongs to the security lane, not to this soak worker.

4. **Coverage gate repaired with real tests.** Reproduced locally with CI's
   exact producers and arguments
   (`.github/workflows/quality.yml` `coverage-gate`): at the pre-sync base the
   failure is `scripts/soak/run_soak.py` at **46.2% of 658 changed lines**
   (need 90/80 per file); `pg_learnings.py` and `tasks.py` already passed.
   `tests/test_soak_promotion_gates.py` grew 84 → 143 tests
   (inventory delta +59, recorded in
   `docs/testing/inventory-notes/m3a-860-multi-replica-soak.md`), covering the
   docker/CLI seams, replica env contract, session-group kill semantics,
   readiness windows, nginx render/mount, teardown log capture, the seeded
   load-mix workers and transport-failure accounting, the claim-probe race and
   forensic cleanup, SIGTERM drain escalation, the config-identity hashes, and
   two full `main_async` orchestration runs (SIGTERM and SIGKILL) asserting the
   fail-closed promotion verdict `["sustain_duration", "exact_rc_artifact"]`.
   Post-repair: **98.6% statements / 90.1% branches** on run_soak.py;
   `uv run python scripts/check-diff-coverage.py <xml> --base e12e1128` →
   `ok: every measured file this change touches is at or above 90% lines /
   80% branch arcs`.

## Fresh checks (this worktree, post-sync HEAD)

| Command / inspection | Result |
|---|---|
| `git merge origin/develop` | clean, `464cea2cd`; merge base now `e12e1128` |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | passed (3519 files) |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 143 passed |
| `uv run pytest packages/maistro-core/tests/backlog/test_markdown_migration.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | 63 passed, 6 skipped |
| `uv run pytest packages/maistro-core/tests --timeout=30 -q` (coverage producer, CI-exact) | 16713 passed, 1213 skipped |
| `uv run pytest packages/maistro-server/tests --timeout=30 -q` (coverage producer) | 647 passed, 10 skipped |
| `uv run pytest tests/ tests/test_model_check_consumer_claim.py packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30 -q` (scripts producer) | 6029 passed, 139 skipped |
| canvas / evolve / rsi / bootstrap producers (publish set) | 553 / 998+1 env-failed / 1735+1 env-failed / 260 passed |
| `coverage report --fail-under=87` on local subset | 92% — floor met (CI's real measurement adds MinIO/Postgres producers, so the true number is ≥ this) |
| `scripts/check-diff-coverage.py --base e12e1128` (full 3-producer data) | **passed** |
| `scripts/check-suite-inventory.py --suite tests` (and core, server) | ok, delta recorded |

Environment-only failures, not introduced by this branch: the two rsi
`test_real_container_*` legs need a working nested-Docker sandbox (branch
touches no `packages/maistro-rsi` file; CI's `coverage (no services)` job was
green at head 49a22c6f).

## Acceptance (unchanged by this repair)

This round makes the harness's own CI green and its evidence honest; it does
NOT manufacture the production soak the issue demands. The exact-RC and
four-hour gates remain fail-closed by design, the process-local rate limiter
still contradicts the "cannot be bypassed by replica selection" criterion
(`packages/maistro-server/src/maistro_server/api/rate_limit.py`, and
`test_replica_selection_has_an_independent_production_allowance` proves the
fresh-allowance bypass), and the load-profile's declared representative-profile
gaps (`docs/testing/soak/m3a-load-profile.md:161-184`) remain open blockers.
Promotion still requires an immutable RC designation plus a real multi-replica
run of at least 14,400 s with the physical-work/recovery oracles.

| Criterion | Status |
|---|---|
| Representative RC load profile | UNRESOLVED — profile exists; declared gaps are blockers |
| ≥2 production replicas exercised | PARTIAL — harness drives 2 host-process replicas; production Compose replicas unproven |
| Sustained load with leak/pool/lease telemetry | UNRESOLVED — 60 s preflights only; 14,400 s gate untouched by design |
| Exactly-once admission across replicas | UNRESOLVED at production scale — probe logic tested, real multi-replica race unproven |
| Rate limiting not bypassable by replica selection | UNRESOLVED — process-local contract contradicts the criterion |
| Telemetry with explicit pass/fail thresholds | PARTIAL — harness emits all metrics; production-scale observations missing |
| Kill/restart one replica mid-work | PARTIAL — drain/failover/rejoin proven on host processes; physical Attempt recovery unproven |
| Long-running soak of the exact RC artifact | BLOCKED — no immutable RC designated; gate fail-closed by design |
| Findings filed/reclassified | UNRESOLVED — no external workflow mutations permitted |
| Machine- + human-readable evidence tied to hashes | PARTIAL — pack exists and is hash-bound; not the promoting soak |

## Handoff

**NEEDS-DEEP-REVIEW** on the two decisions above worker authority:
(a) designate the immutable RC + production topology (or formally re-scope the
exact-RC AC), and (b) the rate-limit AC vs the deliberate process-local
contract — a cluster-wide limiter is a production feature change, not soak
tooling. The DevSkim evidence-corpus glob (precedent: `**/benchmarks/corpora/**`)
should ride the security lane. Everything else this round is committed and
green: sync `464cea2cd`, harness CI repair, inventory delta, this note.
