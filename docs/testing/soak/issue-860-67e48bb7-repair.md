# Issue #860 — bounded repair validation (67e48bb7)

## Frozen scope

Issue #860 only, branch `auto-860`, starting HEAD
`783821d2b59be5b2d04cb11d66f98324c30886c6`, base
`ab8b3737fa64f8d840f421ef87ca506c509444ff`. Worktree initially clean.
Writer interpretation: the lane explicitly requests repair and a local commit.
No current-job check logs supplied; inspected the supplied historical check-3.log
and prior result. No GitHub mutations or ref updates.

Process in order: historical schema-fence failure; exact vulture scan; soak
acceptance verification. Candidate repair files frozen to
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`, its existing
`tests/persistence/test_pg_learnings.py`, `quality/vulture-baseline.json` only
for executed scanner evidence, an inventory note if tests change, and this
report. Soak runner/tests, deployment/profile docs, middleware and relevant
ADRs are read-only evidence. No competing execution or authorization path.

Initial evidence: the schema test already lists the three validation columns
missing from the historical failure. Reproduce before editing. The prior report
claims passing checks but cannot substitute for this round's execution.

## Validation

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. Historical failure does not reproduce; no schema/test edit justified. Database-dependent skips are not live concurrency proof.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1322 reviewed identities / 1322 findings, zero unclassified or never_allowlist. No ledger amendment justified.

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed, including both production-middleware replica-selection counterexamples and fail-closed artifact checks.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.

Schema and scanner items complete without a repair. No tests added or modified,
so no inventory delta is necessary.

## Production acceptance review

Read repository instructions and accepted ADR-081626-f383 (canonical Attempt
leases/fencing), ADR-083026-a91e (unmeasured metrics absent, not zero), and ADR-085
(per-principal rate limiting). Admission identity is not physical-work proof;
local enforcement is not replica-independent enforcement. No ADR reconciliation
permits waiving these acceptance criteria or introducing a parallel authority.

| # | Acceptance | Executed evidence / remaining gap |
|---|---|---|
| 1 | Representative RC load profile | UNVERIFIED. Inspected `m3a-load-profile.md`: one API key, absent successful model/tool calls, Workspace population, Graph fan-out and Design/Canvas coverage. No immutable RC configuration supplied in this dispatch. |
| 2 | Two production replicas | UNVERIFIED. Inspected `deploy/docker-compose.prod.yml`: two application services plus shared services; host preflight is not that deployment. ASGI test instances do not establish live production replicas. |
| 3 | Sustained saturation/reclaim/leak/restart load | UNVERIFIED. Executed unit checks are not sustained-load observations; no long production soak executed in this round. |
| 4 | No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels the admission-probe Run without executing it. Passing admission checks cannot prove Attempt side-effect uniqueness or Goal reconciliation. |
| 5 | Replica-independent rate/security/degraded enforcement | UNVERIFIED with counterevidence. Executed `tests/test_soak_promotion_gates.py:439`: same identity gets `[200, 200, 429]` independently on each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:94` constructs a process-local limiter. No shared-allowance result claimed. |
| 6 | Production telemetry and explicit thresholds | UNVERIFIED. Profile has thresholds but documents driver-loop versus application-loop measurement gaps; unit checks cannot establish production lock/query/queue/leak observations. |
| 7 | Kill/restart during active work with fencing/recovery | UNVERIFIED. No live active-work kill/restart performed; process rejoin and queued admission cleanup are insufficient. |
| 8 | Long exact-RC artifact/config soak | UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly returns `ok: False` for host-preflight artifact identity; executed gate tests preserve that rejection. No supplied immutable image/config selection. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED. This report records limitations; historical disposition is not established by local tests. GitHub mutation prohibited. |
| 10 | Machine/human evidence bound to exact production hashes | UNVERIFIED. No new production evidence pack; this report records local validation only. |

## Handoff

**BLOCKED**, not merge-ready. Only this report changes. The historical failing
test and requested scanner gate currently pass; manufacturing a code/ledger
change would not address actual evidence. No gates, source, tests, ledgers,
authorizations or runtime configuration changed. No deployment or GitHub action.

Next: select the immutable RC image/configuration and representative workload,
provide production-path physical-Attempt/recovery and application telemetry
observers, and resolve the replica-local allowance mismatch. Then execute the
long production soak and publish hash-bound evidence. Repeating the host
preflight or these already-passing CI repairs cannot resolve those prerequisites.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "resolve production RC/workload prerequisites"}`. Issue #860 remains open
and unresolved; the local commit is a validation handoff, not integration approval.
