# Issue #860 repair checkpoint — job 7b3842fe

## Frozen scope

One assigned item: issue #860 on `auto-860`, starting at
`3ee0edd79b8defbeedf8757b7a2c8b32de0208bc`, base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Starting worktree clean.
No remote mutations or develop sync requested by evidence.

Repair/validation surfaces: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`quality/vulture-baseline.json` (only if the mandated scan identifies actual debt),
this report, and an inventory note if tests change. Read adjacent architecture,
ADRs, configuration and tests only to evaluate these surfaces.

Supplied prior `98a11313167b41a98a420abfda80c292/check-3.log` reports
24 schema statements versus 21 expected. This is historical evidence, not a
current failure until reproduced. Current job directory has no check logs.
Prior result `943b95d56ed44f05b99d979754bd6193/result.json` reports BLOCKED;
its soak/promotion claims must be independently checked.

Assumption: writer repair role applies. Exact RC/deployment identity has not
been supplied; do not substitute host-process preflight for release evidence.

## Results

- Mandated vulture scan PASS: 1323 findings / 1323 reviewed identities, zero
  unclassified; no ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped. Historical schema failure does not reproduce;
  the current independent expectation includes the three validation audit columns.
  No speculative schema/test repair warranted. PostgreSQL skips are not live proof.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3270 files).
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: 66 passed. Covers production middleware instances, admission
  backpressure, process-group metrics, and rejection of preflight artifact claims.

Read the ten acceptance criteria from the captured issue body. Read ADR-081
(Proposed), ADR-085 (Accepted), ADR-081426-1f7c (Accepted), and ADR-081626-f383
(Accepted). Reconciliation: physical execution identity is Attempt; Run admission
counts cannot prove physical exactly-once execution. The fencing ADR expressly
excludes expiry takeover; do not invent a competing reclaim authority. ADR-085
requires principal-keyed limits but does not define shared-store semantics.

- Replayed `docs/testing/soak/evidence/m3a-round43-shakedown.json` through the
  current imported `failed_promotion_checks`: fails `sustain_duration` and
  `exact_rc_artifact`; measured duration 420.09 seconds versus 14400 required.
  Asserted both failures and `preflight_artifact_check()['ok'] is False`.
  This checks evidence rejection, not historical observations' validity.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified /
  discovered lifecycles.
- `git diff --check`: PASS.

## Acceptance disposition

| # | Criterion | Executed evidence / outstanding requirement |
| --- | --- | --- |
| 1 | Representative RC profile | UNVERIFIED. Read `m3a-load-profile.md`: one API key, no concurrent Workspace population, Graph fan-out, successful model/tool traffic or Design/Canvas coverage. RC applicability not established. |
| 2 | At least two application replicas | UNVERIFIED for RC deployment. Executed two real middleware instances in ASGI tests, not two deployed RC replicas. |
| 3 | Sustained saturation, reclaim, retries and leaks | UNVERIFIED. Current evaluator rejects the historical 420.09-second window against its four-hour minimum. Short metrics tests cannot establish long-window properties. |
| 4 | Physical work uniqueness and reconciliation | UNVERIFIED. Admission receipt tests pass but do not establish Attempt-level side effects, scheduled workload execution or sustained Goal reconciliation. |
| 5 | Replica-independent security/rate/degraded behavior | Not proven; aggregate allowance is falsified by executed `test_replica_selection_has_an_independent_production_allowance` (authenticated and unauthenticated). Same identity gets `[200, 200, 429]` independently on both instances. `main.py:648` installs this production middleware; `api/rate_limit.py:94` constructs its per-instance limiter. Other security properties under RC load remain UNVERIFIED. |
| 6 | Complete metrics and thresholds | UNVERIFIED. Process-group sampler tests pass. Profile explicitly distinguishes driver-loop from application-loop latency and lacks complete worker/long-window metrics. |
| 7 | Active-work replica kill/restart recovery | UNVERIFIED. No live replica restart in this round; admission/terminal Run counts cannot establish physical fencing or recovery. |
| 8 | Long-running exact RC/configuration | BLOCKED. No selected immutable RC/configuration supplied. `run_soak.py:730` explicitly rejects host-process artifact equivalence; executed CLI regression tests enforce rejection. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED externally. Existing local findings are not proof of current external disposition. No GitHub mutations permitted or performed. |
| 10 | Hash-tied machine/human RC evidence | UNVERIFIED. Historical evidence is present but fails the current evaluator; no new qualifying RC evidence produced. |

## Handoff and stop

Only this report changed. No production code, test, ledger, grant or gate changes
were justified by the supplied failure or mandatory scan. No tests added or
modified; inventory delta zero, so no inventory note needed. Existing work is
preserved. No deployment or GitHub changes performed. This is not a develop-sync
conflict and no merge was attempted.

Verdict: BLOCKED, not integration approval. Next: designate immutable RC
images/configuration and workload applicability; resolve replica allowance
semantics with the responsible owner; use an exact-topology runner with physical
Attempt correlation and application metrics, then execute the required sustained
window on that unchanged RC. Do not repeat the obsolete schema repair or bank
nonexistent vulture debt. Do not relabel emulator evidence as promotion evidence.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0
issues; errors 0 validation commands; 6 DB-dependent test skips. Commit this
checkpoint locally.

## Reverification at 0460e5c9 (2026-10-20)

The assigned job starts clean at `0460e5c91151fc3e372a744e0cf333cef4681542`.
The current job directory contains no `check-*.log`; prior-job logs are not
present in this worktree and are not treated as this round's validation. Read
the captured #860 acceptance body and the current soak profile, then re-ran:

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **84 passed**.
  In particular, `test_replica_selection_has_an_independent_production_allowance`
  passing proves the middleware's known per-process behavior: identical
  authenticated and unauthenticated identities each get `[200, 200, 429]` on
  each separate replica. It does not prove replica-independent aggregate
  enforcement; it falsifies that criterion as currently worded.
- No RC images/configuration or new machine evidence were supplied. Existing
  `m3a-load-profile.md` explicitly makes the host-uvicorn emulator
  non-promotional and requires 14,400 seconds plus exact artifact identity.
  Its own remaining gaps also exclude concurrent Workspaces, Graph fan-out,
  successful tool/model/Canvas/Goal workloads and Attempt-level physical-work
  proof. None of these can be claimed from the executed unit suite.

Reconciliation: ADR-081626-f383 makes Attempt lease/fencing the physical
execution authority and explicitly does not define lease-expiry takeover; the
schedule probe only tests admission and cancels its unexecuted queued Run.
ADR-046 is superseded by ADR-082126-f69c, which makes recurrence produce
canonical Runs. ADR-056's older task-recovery contract is not evidence that
physical failover currently works. The middleware likewise documents a
process-local limiter per #842; making its budget cluster-wide would be a
separate architecture/runtime change, not something this issue's emulator can
prove. No behavior or policy was changed and no new tests were added.

Disposition remains **BLOCKED**: the rate-limit criterion is falsified, and the
exact-RC, four-hour, representative workload and physical recovery criteria are
unverified. An acceptance-complete soak cannot be performed without an
identified production RC/configuration and fixes or an explicit accepted
resolution of the rate-limit contract. No GitHub action taken.
