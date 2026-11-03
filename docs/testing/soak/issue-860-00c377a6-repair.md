# Issue #860 — repair checkpoint 00c377a6

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`9833a977be8bdc3619ffb86d1e472e3216d5bdb4`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
No GitHub mutations or ref changes. Process the supplied dispatch snapshot only.

Files eligible for repair: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
its production counterpart `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`quality/vulture-baseline.json` (only if the required scan demonstrates debt),
an inventory note if tests change, and this report. Inspect the existing soak runner,
its tests, profile, and relevant ADRs for acceptance, without expanding implementation.

## Initial evidence

- Current job directory contains no `check-*.log` files.
- Supplied historical `98a113.../check-3.log` reports schema fence test expecting
  21 DDL statements against 24 observed. Reproduction pending; do not assume current failure.
- Supplied previous result says BLOCKED, with production soak criteria unverified.
  This is a claim to validate, not promotion evidence.
- Ambiguity: assignment asks CI repair plus full issue acceptance. Proceed with
  evidence-led focused repair; leave production acceptance explicitly unverified
  if the required exact-RC evidence is unavailable.

## Fresh results

- Required vulture scan: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified and never-allowlist. No ledger edit justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce: the ordered DDL
  expectation already includes all three validation audit columns (lines 177–179).
- Extracted all ten acceptance criteria from the supplied issue body. Neither
  a designated immutable RC artifact nor its configuration is supplied.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q`:
  89 passed. Combined with the core suite: 126 passed, 6 skipped.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run python scripts/check-doc-links.py`: PASS, 2687 Markdown files,
  zero broken relative links.
- `git diff --check`: PASS. Validation used 1200-second command timeouts.

## Architecture and acceptance

Read repository instructions, documentation authority hierarchy, accepted
ADR-081226-a66b and ADR-081626-f383, and proposed ADR-081. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt; receipt queues cannot become
execution authorities. The fencing ADR explicitly leaves expiry takeover out
of its current contract. The issue cannot authorize inventing reclaim semantics.
ADR-081 is proposed, not accepted deployment authority.

| Acceptance criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC workload | `m3a-load-profile.md:163` explicitly omits multi-user/Workspace, Graph fan-out, successful tool/model, Canvas and Goal/background workloads. Complete coverage UNVERIFIED. |
| At least two production replicas | Executed two-instance ASGI probes; these are not deployed production replicas. Production exercise UNVERIFIED. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, leaks and shutdown | Sampler/accounting regressions pass, not a sustained soak. UNVERIFIED. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal | Admission and receipt tests pass, but do not observe physical work under production load. UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | `tests/test_soak_promotion_gates.py:439` passes for authenticated and pre-auth identities: each replica independently returns 200, 200, 429. Production middleware documents N-times aggregate allowance at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`. Local enforcement proven; cluster-budget non-bypass contradicted under that interpretation. Full criterion UNVERIFIED pending contract reconciliation and production soak. |
| Complete production metrics with thresholds | Profile provides partial thresholds; driver loop lag is not application loop lag. Full query/lock/pool, worker/RSS/fd/queue/error/timeout evidence UNVERIFIED. |
| Kill/restart during active work with drain/fencing/recovery | Unit boot/evidence checks pass; no live active-work recovery oracle executed. UNVERIFIED. |
| Long-running exact-RC artifact/configuration soak | `scripts/soak/run_soak.py:744` always rejects host-process preflight as exact RC. CLI regression tests pass but are not four-hour runs. UNVERIFIED; blocked. |
| Findings filed/reclassified before promotion | No new live-load finding claimed and no GitHub mutation performed. External filing/reclassification UNVERIFIED. |
| Machine/human evidence tied to image/package/commit/config hashes | This report identifies the tested commit, not a production image/configuration. Exact-artifact soak evidence UNVERIFIED. |

The production-router probe at `tests/test_soak_promotion_gates.py:564` also
passes while observing admission-instance 200 and peer 404 for the same receipt.
That is a visibility limitation, not proof of duplicated physical work.
Production schema inspection confirms the advisory transaction lock precedes
all upgrades in `PgLearningStore.ensure_schema`; its passing fake-connection
test does not establish live PostgreSQL concurrency (six DB tests skipped).

## Disposition

BLOCKED on issue acceptance, with no reproduced CI repair target. Only this
report changed; no tests, production code, inventory counts, gates, ledger or
grants changed. No inventory delta is necessary. Local commit is a handoff,
not integration approval. Do not repeat this unchanged CI-repair assignment as
though it could establish production acceptance.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0.
Next: designate immutable RC images/configuration; complete representative
workloads, physical-work and metrics oracles; reconcile aggregate rate-budget
acceptance with existing authority; run and publish the required long soak.
