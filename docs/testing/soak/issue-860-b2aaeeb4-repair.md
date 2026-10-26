# Issue #860 — b2aaeeb4 repair checkpoint

## Frozen scope

- Single assigned item: #860, branch `auto-860`, starting HEAD
  `61d3fd4b11bac905157696428eea008a3ce98e0e`, base
  `435dc1937e0407ab4de198ffcced49860bb14ad2` (both present locally).
- Initial worktree clean; no incoming edits to salvage.
- Inspect the supplied dispatch snapshot and prior result; do not re-fetch issues/PRs.
- Validate the reported learning-schema failure, exact vulture gate, and existing
  soak promotion tests. Read their production paths and relevant ADRs.
- Candidate edit surfaces: this report; `quality/vulture-baseline.json` only if
  the exact scan identifies retained unbanked identities; schema test/source or
  soak test/source only if fresh evidence identifies a focused repair; inventory
  note only if tests change. Do not expand into adjacent issues or authorities.

## Initial evidence / ambiguity

No `check-*.log` files exist in the supplied current job-directory listing.
The explicitly supplied prior `98a11313.../check-3.log` reports 24 schema
statements against 21 expected; this is historical evidence, not a current
failure. The supplied prior result is BLOCKED for missing exact-RC evidence.
Assumption: this is a writer CI-repair round; prove current failures before
editing code or a ledger. An undesignated RC cannot be invented by the worker.

## Fresh validation checkpoint

- Exact requested vulture scan: PASS, 1323 findings / 1323 reviewed identities,
  no unclassified or forbidden findings. Gate-selected baseline `4aa68edc0b6b`.
  No unbanked identity exists to amend; ledger unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped (1.49s). Historical failure does not reproduce.
  Current test independently includes the three validation audit columns at
  lines 173–175. Skips do not establish live database safety.
- Supplied issue body has ten acceptance criteria. Current profile explicitly
  excludes representative workloads and labels the runner preflight-only;
  source confirms `preflight_artifact_check()` always returns false.

Both commands used a 1200-second timeout. No speculative source/test/ledger
repair is justified by these results.

## Completed focused checks

Commands below used a 1200-second timeout; all passed:

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  66 passed in 2.22s (combined with schema tests: 103 passed / 6 skipped).
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: all named components and
  shipping backends exist. This does not certify a running deployment.
- `uv run python scripts/check-merge-markers.py`: no tracked conflict markers.
- `uv run python scripts/check-backlog-consistency.py`: 168 items consistent.
- `git diff --check`: passed.

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; b36a extends the older
lease contract with renewal/reclaim through canonical authority. No alternate
scheduler, recovery authority or principal resolver is justified by #860.
ADR-085 requires principal-based rate identity; local enforcement does not
waive this issue's replica-selection criterion.

## Acceptance against reachable behavior

| Criterion | Executed evidence or outstanding requirement |
| --- | --- |
| Representative RC profile | UNVERIFIED. `m3a-load-profile.md:151–170` explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and background reconciliation. No approved applicability exclusions supplied. |
| At least two deployed application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26–78` defines two replicas; no exact-RC deployment was run here. ASGI instances in regressions are not deployed replicas. |
| Sustained saturation, queues, expiry/reclaim, retries and leaks | UNVERIFIED. Tests run in seconds, not the required long window. No fresh sustained metrics captured. |
| No duplicate physical work | UNVERIFIED. Profile lines 193–203 acknowledge that the one-occurrence probe cancels its queued Run without executing physical work; receipt/admission counts cannot prove Attempt fencing. |
| Rate/security/degraded non-bypass | UNVERIFIED at required deployment scope. Fresh `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) observes `[200, 200, 429]` independently on two real middleware instances for the same principal/client. Production wires it at `maistro_server/main.py:648`; `api/rate_limit.py:93` creates process-local state. The backpressure route test passes through real queue/spine wiring but is not a distributed-security soak. |
| Complete telemetry and explicit thresholds | UNVERIFIED for RC. Profile documents missing application-loop/worker and long-window observations; driver-loop lag cannot stand in for application-loop lag. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED. No deployed active-work fault injection run; process rejoin and terminal rows alone are insufficient. |
| Long-running exact RC/config, repeated after runtime changes | BLOCKED / UNVERIFIED. No immutable RC/config designated by assignment. `run_soak.py:730–741` explicitly rejects its host-process topology and line 1552 wires that result into evidence. Fresh CLI regression rejects synthetic four-hour evidence with missing/null/preflight artifact identity; it is not an actual four-hour soak. |
| Findings filed/reclassified | Limitations recorded locally here; external filing UNVERIFIED. No new load run and no GitHub mutations authorized. |
| Machine/human evidence tied to exact hashes | UNVERIFIED for RC. Starting source head identified, but no promoted-image/config identity or corresponding fresh machine series. Historical artifacts are not recertified. |

The existing schema test independently names all 24 upgrades and asserts the
transaction/advisory-lock ordering (`test_pg_learnings.py:132–192`), matching
production `pg_learnings.py:215–216`; the old 21-statement failure is stale.
The task route maps the canonical concurrency exception to 429/Retry-After
(`maistro_server/api/tasks.py:117–125`), as exercised by the passing route test.
These are bounded regression results, not release acceptance.

## Handoff / stop condition

**BLOCKED**, not promotion or integration approval. Current CI-repair symptoms
are absent; do not amend a matching debt ledger or weaken gates. Exact RC/config
selection remains UNRESOLVED, not permission to invent release identity. Next:
release owner supplies immutable RC/config and supported workload scope; complete
representative production-path traffic, physical-work/recovery observation and
telemetry, reconcile replica-selection expectations via canonical security, then
execute the long-duration soak and publish hash-bound evidence.

Only this report changed. No tests added/removed: inventory delta zero, no new
inventory note required. All inherited work preserved; no remote actions. Local
commit required for handoff. The inherited branch-wide diff is not certified by
these focused checks.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC designation and production-soak prerequisites"}`.
