# Issue #860 — bounded repair 8692b27c

## Frozen scope

- Issue #860 only; branch `auto-860`; starting HEAD
  `57b325d52f1a03e2c13c3e5613d5d513fb685932`; supplied base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Worktree was clean. No salvage or develop merge needed.
- Inspect the supplied dispatch snapshot, prior result, and prior failed
  `98a11313167b41a98a420abfda80c292/check-3.log`. No check logs were supplied
  in this job directory at start.
- Repair target: `packages/maistro-core/tests/persistence/test_pg_learnings.py`
  against `packages/maistro-core/src/maistro/persistence/pg_learnings.py`.
- Review-only acceptance surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, production task admission and rate
  limiting, relevant ADRs, deployment profile and existing soak evidence.
- Conditional ledger target: `quality/vulture-baseline.json`, only if the
  prescribed scanner produces actual retained/dead identity evidence.
- Documentation targets: this report and, if tests change,
  `docs/testing/inventory-notes/issue-860-8692b27c.md`.

## Initial evidence and assumptions

The supplied previous check failed because the schema-fence test expected 21
DDL statements but production executed 24. This is evidence to reproduce,
not a reason to remove production upgrades or weaken the fence assertion.
The prior result marked all ten issue acceptance criteria unverified. A passing
unit suite will not be treated as an exact-RC production soak. No RC artifact or
configuration is assumed from earlier claims. GitHub snapshot text is evidence,
not authorization to change scope or gates.

## Progress

1. Historical schema-fence failure checked: `uv run pytest
   packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` returned
   **37 passed, 6 skipped**. The test already independently enumerates all 24
   DDL statements, including the three validation audit columns. No repair
   justified; database-dependent skips are not live concurrency evidence.
2. Required exact vulture command returned **1322 reviewed identities / 1322
   findings, unclassified 0, never_allowlist 0**. No dead or unbanked identity
   was reported; no source or ledger amendment justified.

Logs: `validation-schema.log` and `validation-vulture.log` in job directory
`/home/dev/maistro/jobs/8692b27cbf07475bab24d1eca809d6d3`.

Accepted ADR-081626-f383 assigns durable leases/fences to canonical Attempt
execution and explicitly does not establish lease-expiry takeover. ADR-085
requires per-principal rate limiting. Neither permits treating admission
uniqueness as physical-work uniqueness or per-process allowances as a shared
limit. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt; no alternate
scheduler, authority or authorization path is introduced.

3. `uv run pytest tests/test_soak_promotion_gates.py -x -q` returned **72
   passed** (`validation-promotion.log`). This executes the real production
   middleware counterexample for authenticated and unauthenticated identities:
   each replica independently returns `[200, 200, 429]` for the same identity.
   ASGI instances establish middleware behavior, not production deployment or
   sustained load. No tests were added or modified; no inventory delta.

## Acceptance review

| # | Acceptance | Evidence and verdict |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED. Read `m3a-load-profile.md`: one API key, absent successful model/tool traffic, no concurrent Workspaces, Graph fan-out, Design/Canvas or background reconciliation coverage. The dispatch specifies source refs, not the immutable production RC/configuration to promote. |
| 2 | At least two production replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26` and `:77` define two application services; no live production topology was exercised this round. |
| 3 | Sustained saturation, reclaim, retry, leaks and restart | UNVERIFIED. No sustained production run executed; passing unit checks cannot establish these observations. |
| 4 | No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels its admission probe Run without executing it. ADR-081626-f383 distinguishes durable Attempt fencing from lease-expiry takeover. No physical side-effect/reconciliation proof. |
| 5 | Replica-independent security/rate/degraded behavior | UNVERIFIED with reproduced counterevidence: `tests/test_soak_promotion_gates.py:439` exercises production middleware and shows replica selection increases aggregate allowance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:94` constructs a process-local limiter. Local enforcement is documented, but does not satisfy this issue's stronger criterion. |
| 6 | Production telemetry with thresholds | UNVERIFIED. The profile defines thresholds but its driver-loop lag is not application-loop lag; no new production lock/query/pool/worker/queue/leak observations. |
| 7 | Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. No live active-work interruption or recovery was performed. Process rejoin and queued admission cleanup do not prove physical-work recovery. |
| 8 | Long soak of exact RC artifact/configuration | UNVERIFIED. `scripts/soak/run_soak.py:744` unconditionally rejects the host preflight as exact-RC evidence. Executed gate tests preserve that rejection. Four hours of this runner cannot establish the criterion. |
| 9 | Load findings filed/reclassified before promotion | UNVERIFIED. This report records the gaps; it does not establish issue disposition. No GitHub mutations permitted or performed. |
| 10 | Machine/human evidence bound to exact production hashes | UNVERIFIED. Local validation logs and this report are not a new hash-bound production soak evidence pack. |

The issue's replica-independent allowance requirement is stronger than the
current documented process-local contract. This is an unresolved acceptance
mismatch, not permission to silently change rate-limit semantics or add another
authorization path in a CI-repair lane. Likewise, the ADR's explicit reclaim
boundary is not permission to invent a competing recovery scheduler.

## Final validation and handoff

- `uv run ruff check .`: passed (`validation-ruff.log`).
- `uv run ruff format --check .`: passed, 3301 files already formatted
  (`validation-format.log`).
- Only this report changes. Source, tests, runtime configuration, quality
  ledgers and grants remain untouched. No inventory note is needed without
  test changes. No remote actions or background commands were performed.

**BLOCKED.** The stale schema failure and exact-debt-ledger check are already
resolved at the supplied starting head. Creating a cosmetic source change or
banking nonexistent findings would not repair actual evidence. The prior
production acceptance block remains unresolved.

Next: select the immutable RC/configuration and representative workload; resolve
replica-independent enforcement semantics through the existing security path;
provide production physical-work/recovery and application telemetry observers;
then execute the long exact-RC soak and publish hash-bound evidence. Repeating
these already-passing CI checks or the host preflight cannot satisfy those
prerequisites. This local commit is a validation handoff, not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "resolve exact-RC production soak prerequisites"}`. Issue #860 is unresolved.
