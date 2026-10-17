# #860 CI repair checkpoint

## Frozen scope

- Issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `7b1b5e17bbb784350e076394ef540c0a276d90a9`; working tree initially clean.
- Read-only inputs: repository instructions, execution/release/rate-limit ADRs, existing `scripts/soak/`, `tests/test_soak_promotion_gates.py`, soak documentation/evidence, adjacent package tests, vulture checker and its emitted source identities.
- Permitted edit targets: this handoff, `quality/vulture-baseline.json` for reviewed retained identities reported by the required checker, and only evidence-backed #860 repairs/tests (with inventory delta if tests change).
- No unrelated branch/base differences will be reconciled in this round. No GitHub mutations.

## Initial evidence and assumptions

- The supplied prior result exists and reports BLOCKED at this exact starting HEAD; its claims require fresh validation.
- The job directory snapshot contains `events.jsonl`, `manifest.json`, `prompt.txt`, and `state.json`; no `check-*.log` files were supplied. Driver results are therefore unavailable, not presumed passing.
- No exact promotion RC image/configuration is identified in the assignment. Existing host-process preflight cannot substitute for a >=4-hour exact-artifact soak.
- Proceed as writer for the explicit CI repair, preserving the blocked acceptance status unless fresh executed evidence proves otherwise.

## Progress

- Required exact-debt-ledger command freshly PASSed: 1402 findings / 1402 reviewed identities, unclassified=0, never_allowlist=0. No emitted unbanked identity exists to repair; no ledger amendment is warranted.
- Reviewed instructions, existing evidence/profile and gate tests, and accepted ADR-081426-1f7c (Attempt runtime identity), ADR-081626-f383 (canonical store fencing), ADR-082426-82c7 (occurrence admission), ADR-085 (principal rate limiting). ADR-081 remains Proposed and supplies no waiver.
- Production `RateLimitMiddleware` explicitly constructs per-instance `InMemoryRateLimiter`; #860's cluster non-bypass requirement cannot be declared satisfied by local overload probes. No competing authorization/store path will be introduced to force acceptance.
- Existing tests exercise real limiter instances and missing/null/preflight artifact rejection. Fresh execution completed below; no production code or tests changed.

## Fresh validation

All commands ran in the assigned worktree, with 1800-second timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 reviewed identities, 1402 findings, zero unclassified/never-allowlist |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 84 passed, 5 skipped, 153.76 seconds; PostgreSQL-dependent coverage skipped, not credited as live validation |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 2624 files already formatted |
| `uv run python -` (import actual driver; evaluate preserved round-6 JSON; assert exact failure list and negative preflight artifact verdict) | PASS: failures are `sustain_duration`, `exact_rc_artifact`; observed duration 90.43 seconds |
| `git diff --check` | PASS |

No tests added or removed: inventory delta is zero and no new inventory note is required. The prior inventory timeout is not relabelled as passing. No new soak was executed.

## Acceptance disposition

| # | Criterion | Freshly checked evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative release profile | PARTIAL: `m3a-load-profile.md` describes a request mix, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas and Goal workers. Applicability for the selected RC remains UNVERIFIED. |
| 2 | At least two production replicas | UNVERIFIED: `deploy/docker-compose.prod.yml:26-60` defines two application services; historical evidence is host-process preflight, not execution of these images. |
| 3 | Sustained saturation/reclaim/retry/leak observation | UNVERIFIED: round-6 JSON `sustain_seconds=90.43` against minimum 14400; regression tests are not sustained load. |
| 4 | Exactly-once/fenced physical work | UNVERIFIED: historical schedule probe cancels the admitted Run (`probe_run_cleanup`); admission uniqueness cannot prove physical Attempt effects or Goal reconciliation. Accepted occurrence and Attempt authority ADRs are preserved. |
| 5 | Rate-limit/security/degraded non-bypass | NOT MET for a cluster-wide allowance: executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes reproduces `[200,200,429]` on each replica for one identity. Local identity/security tests pass; full degraded RC traffic remains UNVERIFIED. |
| 6 | Complete metrics with thresholds | UNVERIFIED: source records driver-loop lag, not application-loop lag. Historical RSS/FD/session series are provisional; full worker counts and sustained pool/lease pressure are not proven. |
| 7 | Kill/restart physical-work recovery | UNVERIFIED: historical exit/rejoin records alone do not correlate physical Attempts, fences and effects; no RC restart executed this round. |
| 8 | >=4h exact-RC soak, rerun after changes | BLOCKED: no designated immutable RC image/config supplied; actual driver emits `exact_rc_artifact.ok=false` at `run_soak.py:1409`. Executed CLI tests reject missing/null/preflight artifact records even at four hours. |
| 9 | Findings classified/filed before promotion | PARTIAL: existing F1-F10 classification/handoff retained, including earliest-invariant attribution for replica boot; external filing UNVERIFIED and prohibited in this lane. |
| 10 | Machine/human hash-tied soak evidence | PARTIAL: historical JSON and human pack exist, with commit/config/PG hashes, but not a promotable application image/config soak. RC acceptance UNVERIFIED. |

## Disposition and next action

**BLOCKED** for issue #860, not integration approval. Explicit CI-repair check is complete with no unbanked debt; do not manufacture a ledger change or weaken the gate. Only this checkpoint report changes in this round. Prior production/test/evidence work is preserved.

Next: designate immutable promotable images/configuration; resolve cluster rate-limit semantics with the owning deployment/security lane; complete production-path workload/physical-effect/metric oracles, then execute and publish a new >=4-hour exact-RC soak. Another emulator shakedown cannot unblock acceptance.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`. Validation complete; this report is the sole file staged for the local checkpoint commit. No production/configuration changes, ledger amendments, or GitHub mutations were made.
