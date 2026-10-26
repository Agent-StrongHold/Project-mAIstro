# #860 repair checkpoint — round 12

## Scope and disposition

**BLOCKED: no promotion approval.** Assigned worktree `auto-860` started clean
at `73b3dc49ef6d9560c2ff911d936c94e7a26f4ad3`. Only issue #860 and its explicit
Vulture CI-repair request were processed. No incoming edits required salvage.
The supplied base resolves; no sync conflict exists. No GitHub mutation occurred.

Read `AGENTS.md`, `CLAUDE.md`, the existing soak profile, evidence, driver gates
and adjacent regression tests. Accepted ADR-081426-1f7c assigns mechanics to
Attempt execution, ADR-081626-f383 assigns fencing authority to the canonical
Run store, ADR-085 requires per-principal rate limiting, and ADR-083026-a91e
forbids invented measurements. ADR-081 is **Proposed**, not accepted authority.
No competing scheduler, execution, event or authorization path is introduced;
`Goal -> Graph -> Run -> NodeRun -> Attempt` remains unchanged. Admission
uniqueness is not treated as physical-effect uniqueness.

The previous job result was read, but its verification claims were not reused
as fresh results. Current job `d0191bd510a048b9b91bfbecd0878347` had no
`check-*.log` files when inspected. Fresh writer logs are in that job directory.

## Executed validation

Commands ran with 600–1800 second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS: 1402 findings / 1402 reviewed identities; zero unclassified or
  never-allowlist findings, no candidate ledger delta. No ledger amendment or
  deletion of retained code is justified by this actual scan.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs`
  — **102 passed, 5 skipped in 10.85s** (`writer-pytest.log`). All five skips
  require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof is claimed.
- `uv run ruff check .` — PASS (`writer-ruff-check.log`).
- `uv run ruff format --check .` — PASS, 2624 files (`writer-ruff-format.log`).
- `uv run python scripts/check-suite-inventory.py --suite tests/` — PASS,
  4198 collected tests (`writer-inventory.log`). No tests added or changed;
  inventory delta is zero.
- `uv run python -` imported the current soak driver, loaded preserved round-6
  JSON, and asserted duration below the minimum and failing gates exactly
  `sustain_duration`, `exact_rc_artifact`. Output: 90.43 vs 14400 seconds;
  `preflight_artifact_check()` is false (`writer-evidence-check.log`).
- Production wiring inspected: `maistro_server/main.py:478` installs the same
  `RateLimitMiddleware` exercised by the regressions. Both authenticated and
  unauthenticated identities receive `[200, 200, 429]` independently on two
  instances. This is reachable middleware behavior, not a live deployment soak.
- `git diff --check` — PASS before commit.

## Acceptance, criterion by criterion

| Criterion | Evidence / remaining gap |
| --- | --- |
| Representative RC profile | PARTIAL: `m3a-load-profile.md` defines mix and thresholds but explicitly lacks multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads. RC representativeness UNVERIFIED. |
| At least two production application replicas | `deploy/docker-compose.prod.yml` defines two, but fresh exact-artifact deployment execution UNVERIFIED. ASGI middleware instances are not production replicas. |
| Sustained saturation, queue growth, reclaim, retry and leaks | UNVERIFIED: evaluated historical 90.43-second evidence is insufficient; no new sustained run executed. |
| No duplicate schedule/task/Run/Attempt physical work; Goal reconciliation | UNVERIFIED: HTTP admission-oracle regressions pass, but mock receipts and a historical occurrence race do not establish unique physical effects or Goal reconciliation under load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for an aggregate principal allowance: executed production-middleware regressions demonstrate another allowance on replica 2. Full RC security/degraded behavior UNVERIFIED. The old shared-store assertion is already retracted; no duplicate prose repair made. |
| Full metrics and explicit thresholds | PARTIAL: profile and live child-process sampler regression exist; sustained PostgreSQL, application-loop, worker, queue, lock, error and leak measurements on the exact RC remain UNVERIFIED. |
| Kill/restart active work with drain/fencing/recovery | UNVERIFIED: no fresh in-flight Attempt/effect correlation; process exit/rejoin is insufficient. |
| Long-running exact RC artifact/configuration soak | BLOCKED: no designated immutable RC/configuration supplied. Current host-preflight always rejects artifact equivalence; historical duration is below four hours. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing local F1–F12 dispositions preserved; external filing UNVERIFIED and prohibited in this lane. |
| Machine/human evidence tied to exact image/package/commit/config hashes | PARTIAL: historical preflight files preserved unchanged; qualifying RC evidence UNVERIFIED. |

## Next action and checkpoint

Only this handoff changes. No code, runtime configuration, tests, ledger or raw
soak evidence changed. Passing static gates cannot resolve the previous block.
The release owner must designate the immutable RC/configuration, resolve the
aggregate rate-limit acceptance mismatch with its owning lane, complete the
representative workload and physical-effect oracles, then execute and publish
a new >=4-hour exact-artifact soak. Do not rerun the host emulator as a substitute.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and
production-path sustained evidence}`. CI-repair validation is complete; issue
#860 is not complete. This handoff is committed locally as the writer checkpoint.
