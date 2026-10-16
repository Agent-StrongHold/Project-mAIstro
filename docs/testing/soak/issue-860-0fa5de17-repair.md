# Issue #860 — repair job 0fa5de17

## Frozen scope

- Assigned issue: #860 only; no GitHub mutations or PR processing.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `48db00e373d047838482f12a52b227ee05306750`.
- Supplied base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Read-only evidence: supplied dispatch context, cited prior result and check-3.log,
  repository instructions/ADRs, soak harness and adjacent promotion tests,
  relevant production task/concurrency code and CI gate configuration.
- Candidate edits: this report; `quality/vulture-baseline.json` only if the exact
  scan establishes retained unbanked identities. No speculative production edits.
- Ambiguity resolved: proceed as writer (explicit assigned repair), not verifier.
- Current job directory contains no driver `check-*.log` files. Prior result is
  BLOCKED and is not treated as fresh acceptance evidence.

## Progress

- Exact vulture scan passed: 1322 findings / 1322 reviewed identities,
  zero unclassified or never-allowlist findings. No ledger repair warranted.
- Cited historical check-3.log is a schema-test mismatch (24 statements vs 21),
  not a scanner failure. Fresh command:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: **110 passed, 6 skipped** in 2.21s. Historical failure did not reproduce.
  Skipped PostgreSQL integration cases are not live deployment evidence.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 53 consumers;
  nonfatal invalid-escape SyntaxWarnings. Gates selected trusted base
  `321cbdb8fe9b`; no provenance override was used.
- Read accepted ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a.
  Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and canonical lease
  authority. The later ADR supplies renewal/reclaim semantics; missing soak
  evidence is not evidence that the mechanism is absent.
- Read complete existing load profile and production-component tests. The fresh
  suite executed same-identity replica probes yielding `[200, 200, 429]` on each
  middleware instance and receipt probes yielding owner 200 / peer 404. These
  are ASGI component observations, not deployed-ingress acceptance.
- `scripts/soak/run_soak.py:744–755` explicitly rejects exact-RC equivalence.
  No longer run of this host-process emulator can satisfy that criterion.
- Production inspection confirms per-instance `InMemoryRateLimiter` at
  `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` and injected
  queue receipt lookup at `api/tasks.py:144`. The schema test already includes
  all three validation-audit columns at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:173–175`;
  production DDL is transaction/advisory fenced at
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–222`.

## Acceptance disposition

| #860 criterion | Fresh evidence and remaining requirement |
|---|---|
| Representative release profile | **UNVERIFIED**. Existing profile is inspected, but lacks concurrent users/Workspaces, Graph fan-out, successful tool/model and Design/Canvas traffic or RC-specific exclusions. |
| At least two production replicas | **UNVERIFIED**. Two-instance ASGI probes executed, not a deployed production topology. |
| Sustained saturation, growth, reclaim, retries and leaks | **UNVERIFIED**. No sustained production load executed this round. |
| No duplicate physical work across replicas | **UNVERIFIED**. Admission assertions are not physical Attempt uniqueness; existing profile's schedule probe cancels its queued Run. |
| Replica-resistant security/rate/degraded behavior | **UNVERIFIED** in deployment. Fresh tests reproduce independent per-instance allowances; local 429 responses do not prove a shared principal budget. |
| Complete telemetry with thresholds | **UNVERIFIED**. Profile thresholds exist; driver loop lag is not application loop lag, and process-group sampling excludes detached workers. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. No physical active-Attempt fault injection executed. |
| Long soak of exact RC/configuration | **BLOCKED / UNVERIFIED**. Runner rejects artifact equivalence by design; no immutable RC image/configuration selected or exercised here. |
| Findings classified before promotion | **UNVERIFIED** for completeness. Local findings preserved; no GitHub mutation authorized or performed. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED** for promotion. Source-bound test results are not an image/package/config-bound production soak pack. |

## Handoff

**BLOCKED**, not merge-ready. Historical CI failure does not reproduce and exact
vulture scan has no unbanked identities. Changing production code or the ledger
without new evidence would be speculative. Only this report changed; no tests
added, so no inventory delta is needed. Existing salvage remains untouched.

Release owner must select immutable RC image/configuration and representative
workload, then execute the profile's >=4-hour production soak with application
telemetry and active physical Attempt failure/recovery. Use canonical admission,
lease and authorization owners, not a parallel execution authority. Any subsequent
code/runtime-config repair requires a new soak. Repeating this same CI-repair
assignment cannot supply the missing release artifact or production evidence.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production soak}.
Local report commit is a handoff only, not integration approval.
