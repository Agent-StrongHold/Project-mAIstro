# Issue #860 — repair validation 1e1b94a4

## Frozen scope

- Sole issue: #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `47b746d249bbf0bd852fe753b59424d7e56903d2`; supplied base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Initial worktree clean; no incoming uncommitted work to salvage.
- Process only supplied dispatch/prior-result evidence, repository instructions, relevant ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, the existing load profile/evidence, production paths reached by those checks, CI gate configuration, and `quality/vulture-baseline.json` if the required scanner identifies retained debt.
- This note is the checkpoint/report file. No GitHub mutations, gate weakening, new execution authority, or unrelated repair.
- Ambiguity: prompt includes verifier and writer instructions. Assignment explicitly says repair/writer and requires a commit; proceed as writer.
- Job directory contains no `check-*.log` at snapshot time. Inspect the explicitly supplied prior failed log instead; do not assume historical claims are current.

## Progress

- Required exact vulture scan passed: 1,323 reviewed identities / 1,323 findings; zero unclassified or never-allowlist identities. No evidence justifies a ledger amendment.
- Supplied historical failed log is the learnings schema-lock test (24 statements vs 21 expected), not vulture. Current rerun pending.
- Read all ten acceptance criteria from supplied dispatch. Current load profile explicitly labels the harness preflight-only, requires 14,400 seconds, and lists missing representative workload and physical-work coverage. No preflight rerun can establish exact RC identity.
- Adjacent tests include production middleware counterexamples to a shared replica allowance; executed in this round (both authenticated and pre-auth cases passed).
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed, 3,270 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 129 passed, 6 skipped. Historical schema-lock failure does not reproduce.
- `uv run python scripts/check-suite-inventory.py`: all 17 suites match, 31,128 unique identities, no duplicates. No tests added/removed in this round; no inventory delta needed.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- Read ADR-081 (Proposed), accepted ADR-085, ADR-081426-1f7c, ADR-082426-82c7 and ADR-082426-e3ff. Physical execution identity is Attempt, not Run; occurrence admission and terminal Run counts cannot prove physical-work uniqueness/recovery. Principal-keyed limiting does not establish shared replica storage. No accepted ADR supplies a waiver for missing exact RC evidence. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged.

## Acceptance review

Executed the current `failed_promotion_checks` against
`evidence/m3a-round43-shakedown.json` by importing `scripts/soak/run_soak.py`
with `uv run python`. Result: `['sustain_duration', 'exact_rc_artifact']`.
Historical JSON observations below were inspected, not re-executed as a live
soak. Passing unit tests are not substituted for promotion traffic.

| Issue criterion | Evidence / disposition |
| --- | --- |
| Representative RC load profile | Profile exists but explicitly omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background work. RC representativeness **UNVERIFIED**. |
| At least two application replicas | Historical JSON contains both replica origins and rejoin/resource observations. Exact production RC deployment **UNVERIFIED**. |
| Sustained saturation, queues, reclaim, retries, leaks | Executed evaluator rejects 420.09 seconds against 14,400 required. Long-window behavior **UNVERIFIED**. |
| No duplicate physical work | Historical task probe observes one Run across 12 submissions; schedule race observes one Run but cancels it without executing. Admission regression tests pass; physical Attempt fencing and Goal reconciliation under sustained load **UNVERIFIED**. |
| Rate/security/degraded behavior non-bypass | Executed production-middleware tests show the same identity independently obtains `[200, 200, 429]` on both replicas. Local enforcement holds, but replica-independent allowance claim is unmet; full concurrent security/degraded acceptance **UNVERIFIED**. |
| Required metrics and pass/fail thresholds | Profile/JSON provide resource and latency records; real uv-child sampler test passes. Driver loop lag is not application loop lag; complete worker/pool/lease/contention coverage **UNVERIFIED**. |
| Kill/restart with drain/fencing/recovery | Historical JSON records SIGTERM, one-second drain, zero drain errors, no escalation, rejoin. Physical recovery/no-duplication under RC load **UNVERIFIED**. |
| Long-running exact RC artifact/config | Host-uvicorn artifact gate deliberately fails; CLI fail-closed regression tests pass, even for synthetic four-hour evidence. Exact RC soak **UNVERIFIED**. |
| Findings filed/reclassified | No external filing completeness established in this round; **UNVERIFIED**. No GitHub mutation permitted or performed. |
| Published machine/human evidence tied to exact hashes | Historical JSON/Markdown exist; JSON has old commit/config/Postgres hashes, `git_clean=false`, no promoted app-image digest. Exact RC publication **UNVERIFIED**. |

## Disposition / handoff

**BLOCKED**. Deterministic gate repair is not currently needed: the exact vulture
scan is clean, and the supplied historical test failure no longer reproduces.
Changing retained identities or runtime code on that basis would be speculative.
Only this report changed; no tests, inventory counts, ledgers, grants or gates
changed. No fresh host-process shakedown was launched because it cannot meet the
exact-artifact acceptance at any duration.

UNRESOLVED release prerequisites: select immutable RC image/configuration and
supported workload scope; reconcile the process-local limiter contract with
#860's replica-selection acceptance; implement/run the representative exact-RC
workload for at least four hours, observing physical Attempts, reclaim and
recovery; classify findings through an authorized actor. Do not approve promotion
by rerunning the unchanged preflight. Existing work is preserved in place.

Validation commands used 600-second timeouts. Commit this report locally, then
verify a clean worktree. Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "RC prerequisites and exact-artifact promotion evidence"}`.
