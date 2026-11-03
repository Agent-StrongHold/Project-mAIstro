# Issue #860 repair — job 98f953e4

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`09435328ed86cc176d21c96ae998475ddc597269`, base
`ab8b3737fa64f8d840f421ef87ca506c509444ff`.
The worktree was clean. No GitHub mutations or integration approval.

Review surfaces: repository instructions, relevant execution/release ADRs,
`scripts/soak/run_soak.py`, the profile documented under `docs/testing/soak/`,
`tests/test_soak_promotion_gates.py`, adjacent soak tests and evidence,
`scripts/check-vulture-baseline.py`, its CI invocation, and
`quality/vulture-baseline.json` only if fresh scanner evidence warrants amendment.
Write surfaces: this report and evidence-justified repairs within those surfaces;
any new tests require an inventory note.

The current job directory contains no driver `check-*.log` files.
The supplied prior result reports BLOCKED, not acceptance. It is historical
context, not fresh validation. The cited prior failed log will be inspected.
Ambiguity: this is an explicitly assigned writer repair, so the verifier-only
no-edit instruction does not apply. No exact promoted RC identifier/configuration
is supplied in the lane assignment; do not manufacture promotion evidence.

## Results

Fresh requested vulture scan passed: 1,322 findings, zero unclassified and
zero never-allowlist findings. No evidence warrants a ledger amendment.
The supplied historical check-3 log is a learning-schema test failure (24
statements versus 21), not vulture. Fresh execution of
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped. No speculative production/schema repair warranted.

Additional fresh checks (all exit 0):

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — 73 passed.
- `uv run python scripts/check-suite-inventory.py` — all 17 suites match;
  31,327 unique identities, no duplicate evidence.
- Inline `uv run python` imported the current runner and evaluated frozen
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`. It asserted rejection
  of `sustain_duration` and `exact_rc_artifact`: observed 420.08 seconds versus
  14,400 minimum. It also asserted the current preflight artifact check is false.
  This re-evaluates historical evidence; it is not a new live soak.

The vulture invocation matched `.github/workflows/vulture-ratchet.yml:82`:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
No tests changed or were added, so no inventory delta is needed.

## Architecture reconciliation

Read repository instructions, the release contract in `ROADMAP.md`, accepted
ADR-081426-1f7c and ADR-081626-f383, the current load profile, runner gates and
probes, adjacent regression tests, and installed production rate-limit middleware.
`Goal -> Graph -> Run -> NodeRun -> Attempt` remains the only execution model.
Physical runtime identity is the Attempt ID; the canonical Run store owns fencing.
The lease ADR explicitly does not define expiry takeover. The release roadmap
also defers task-queue restart recovery to a later horizon. Neither statement
permits claiming that issue #860's broader recovery criterion is proven; the
selected release scope must be reconciled explicitly before promotion. No new
execution or authorization authority is introduced to bypass these boundaries.

## Acceptance evidence

| # | Criterion | Fresh review / executed evidence |
|---|---|---|
| 1 | Representative workload | UNVERIFIED. `m3a-load-profile.md`, Remaining representative-profile gaps, explicitly omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workers. No designated immutable RC/configuration in the lane assignment. |
| 2 | At least two production replicas | UNVERIFIED. `scripts/soak/run_soak.py:744` identifies host-uvicorn preflight, not the promoted production Compose topology. ASGI tests do not prove deployment. |
| 3 | Sustained saturation/retry/leak observations | UNVERIFIED. Executed current evaluator rejects the historical 420.08-second sample against the 14,400-second floor. No fresh sustained load performed. |
| 4 | No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1070` cancels the admission probe's queued Run without execution. Admission deduplication is not proof of physical Attempt or Goal work uniqueness. |
| 5 | Replica-independent security/degradation | UNVERIFIED overall; independent allowances reproduced. `tests/test_soak_promotion_gates.py:439` exercises the real production middleware for both identity classes: each replica permits two requests then returns 429 for the same identity. Production installs it at `packages/maistro-server/src/maistro_server/main.py:648`; process-local semantics are explicit at `api/rate_limit.py:32`. Local enforcement tests cannot prove a shared principal budget. |
| 6 | Complete production metrics/thresholds | UNVERIFIED. Sampler tests pass, but the profile documents driver-loop rather than application-loop lag, and incomplete worker/pool/reclaim coverage. No complete exact-RC time series produced. |
| 7 | Active-work restart, drain, fencing/recovery | UNVERIFIED. No live production Attempt kill/restart executed. Health rejoin and terminal Run counts are insufficient. |
| 8 | Long soak of exact RC/configuration | UNVERIFIED. Both duration and artifact gates reject historical evidence; the current runner's artifact gate is unconditionally false by design. |
| 9 | Findings disposition before promotion | UNVERIFIED. Historical reports do not prove current external filing/reclassification; no GitHub mutations performed. |
| 10 | Machine/human evidence bound to promoted hashes | UNVERIFIED. Historical artifacts exist but do not establish a designated immutable promoted image/configuration or a new qualifying run. |

## Handoff

**BLOCKED**, not merge-ready. Changed only this report; no production code,
ledger, grants, tests or gates changed. The cited CI failure does not reproduce.
This is a documented unresolved handoff, not an implementation completion claim.

Next required inputs/work: designate immutable RC images and runtime configuration;
complete and justify the representative workload and production observability;
reconcile replica-budget and recovery semantics against the supported release;
execute at least four hours on that exact topology, including active Attempt
restart/fencing evidence; publish hash-bound results and findings disposition.
Repeating the same vulture repair dispatch cannot supply these prerequisites.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designated RC and production soak"}`.
A local commit preserves this report; no remote actions or integration approval.
