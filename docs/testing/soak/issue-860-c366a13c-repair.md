# Issue #860 — c366a13c repair checkpoint

## Frozen scope

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting at `5ed42489ada60ddfc14546f828b48bbf9a194db8`;
base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Initial worktree clean; no incoming uncommitted work to salvage.
Process the supplied schema regression and exact vulture gate, then acceptance
validation. Candidate edit files are this report,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, an associated
inventory note, and `quality/vulture-baseline.json` only if the actual scan
requires an authorized repair. Production and soak files are inspected for
acceptance evidence, not an invitation to redesign execution or authorization.

The current job directory contains no `check-*.log` files. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 schema statements
versus 21 expected in the advisory-lock regression. This is historical evidence,
not yet a reproduced failure. Prior result `93757bb2` is BLOCKED on missing
exact-RC soak evidence; its claims will not be treated as fresh validation.

Ambiguity: this is a writer repair assignment, so the verifier-only prohibition
on edits does not apply. No remote mutation, fetch, or merge is needed: the
starting ref resolves exactly and there is no merge conflict.

## Reproduction checkpoint

The exact requested vulture gate passed (1,322 findings / 1,322 reviewed
identities; zero unclassified findings). No ledger amendment is warranted.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped. The historical failure does not reproduce;
lines 175–179 already include the three validation audit columns. Skipped
PostgreSQL tests do not establish live multi-replica schema safety.
No code or test change is justified by the supplied CI failure.

## Executed validation

All commands ran in the assigned worktree with 1,000–1,200 second timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,322 reviewed identities match; exact `.github/workflows/vulture-ratchet.yml:82` arguments |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,301 files already formatted |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |

## Acceptance disposition

The supplied dispatch's issue body has ten criteria. None is established at
promotion grade by this round's deterministic validation:

| Criterion | Fresh evidence and remaining requirement |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Read `m3a-load-profile.md`: the preflight uses one credential and omits concurrent Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background-worker traffic. RC-specific applicability remains to be defined. |
| At least two deployed application replicas | **UNVERIFIED.** Executed two-instance ASGI probes, not production deployment. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks | **UNVERIFIED.** Short deterministic tests cannot prove sustained behavior; no long load run executed. |
| No duplicate physical work | **UNVERIFIED.** Admission counters and mock responses do not establish physical Attempt fencing or Goal reconciliation. |
| Replica-resistant security/degraded behavior | **UNVERIFIED; contrary evidence.** `tests/test_soak_promotion_gates.py:439` passed by observing [200,200,429] independently on two production middleware instances for the same principal/IP. Replica selection increases the aggregate allowance. |
| Required telemetry and thresholds | **UNVERIFIED at promotion grade.** Sampler/gate tests passed, but no production PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry captured. Driver loop lag is not application loop lag. |
| Active-work restart, drain, fencing, recovery | **UNVERIFIED.** No replica killed/restarted during live work this round. |
| Long exact-RC soak, rerun on changes | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:744` explicitly returns false for exact-RC equivalence; its CLI/gate tests passed. No designated immutable RC image/configuration supplied. A longer host-process run would still fail. |
| Classify load findings to earliest broken invariant | **UNVERIFIED for completeness.** Backlog consistency passed; no new load findings or GitHub mutations. |
| Machine/human evidence bound to artifact hashes | **UNVERIFIED.** This report records local validation, not an image/configuration-bound production soak. |

Production reachability checked: `maistro_server/main.py:648` installs the rate
limiter and lines 735/755 mount the task router. The receipt probe at
`tests/test_soak_promotion_gates.py:564` passed by observing 200 on the admitting
queue and 404 on its peer using that real router; `api/tasks.py:146` raises the
404. It uses a shared in-memory canonical admission spine, not a deployed
multi-replica database. These tests meaningfully falsify stronger claims but do
not establish complete production-topology behavior.

## Architecture and handoff

Read repository instructions, `docs/README.md`, accepted
ADR-073126-c4e1 (release/versioning), and ADR-082426-82c7 (occurrence claim).
The release ADR requires promoting the artifacts validated by the RC; no host
emulator or invented RC identity can substitute. The occurrence ADR puts
uniqueness in the canonical Run store, not a second scheduler or claims store.
No change to `Goal -> Graph -> Run -> NodeRun -> Attempt`, authorization,
events, production code, tests, or quality ledgers was made.

Only this report changed. No tests were added/removed; no inventory delta is
needed. The assigned CI-repair investigation is complete with no reproducible
CI defect. The broader issue remains **BLOCKED**, not merge-ready. Required next
input: a release-owner-designated immutable RC/deployment configuration, then
representative long-running production execution and assessment of replica-local
behavior. Repeating this same stale failure log cannot resolve those blockers.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
validation errors 0. Existing work preserved; local report committed for handoff.

