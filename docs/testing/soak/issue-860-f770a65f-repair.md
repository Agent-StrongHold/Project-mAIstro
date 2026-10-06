# Issue #860 — repair checkpoint (f770a65f)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting head: `799555faff5d6513711b1dbcf8f56dab2e9b980d`.
- Supplied develop base: `b6c50ef9900549755d9815254e1749f6f6d83c73`.
- Inspect existing `scripts/soak/`, `tests/test_soak*`, associated server
  rate-limit implementation/tests, production Compose configuration, relevant
  ADRs, soak evidence/profile and quality-gate instructions.
- Run the exact requested vulture scan; change `quality/vulture-baseline.json`
  only if actual findings justify reviewed identity repair. No other ledger edits.
- Planned report file: this document. Add tests/inventory notes only if a
  demonstrated in-scope implementation defect is repaired.

## Initial observations

The worktree was clean and HEAD matched the assigned starting commit.
No driver `check-*.log` files were present in the supplied job directory.
The supplied previous result reports BLOCKED, but is not fresh acceptance proof.
The dispatch issue body has ten acceptance criteria, including an exact-RC
long-running soak, representative production traffic and replica-selection
non-bypass. No remote operations or issue mutations are authorized.

Ambiguity: this dispatch requests a vulture CI repair while the previous result
says that exact scan passed. Proceed by executing it, not inventing dead-code
findings or banking unsupported debt. If the gate passes and production soak
preconditions remain absent, preserve existing work and report the blocker.

## Validation

- Exact requested vulture command passed: 1,336 findings matched 1,336
  reviewed identities; zero unclassified and zero never-allowlist findings.
  It selected baseline `56332162cf63`; no identity repair or ledger amendment
  is justified. Repeating with the resolved supplied base via
  `RATCHET_BASE_REV=b6c50ef9900549755d9815254e1749f6f6d83c73` also passed,
  selecting the same merge-base.
- `git diff --check b6c50ef9900549755d9815254e1749f6f6d83c73...HEAD`
  passed; the earlier whitespace findings are not reproduced.
- Inspected the production Compose reference, current driver and adjacent
  middleware/gate tests. The driver still explicitly rejects its host-process
  topology as exact-RC evidence (`run_soak.py:635-646`). The production limiter
  still constructs an independent in-memory limiter (`rate_limit.py:72`).

## Architecture reconciliation

Read repository instructions and ADR-081426-1f7c (runtime mechanics),
ADR-081626-f383 (canonical Attempt fencing), ADR-085 (per-principal rate
limiting), and ADR-081 (deployment; **Proposed**, not accepted authority).
An admission identity/count is not physical Attempt execution/fencing proof.
No alternate execution, authorization, scheduler or event authority is added.
The documented process-local #842 scope does not waive #860's stronger
replica-selection non-bypass criterion. Exact artifact identity cannot be
repaired by relabeling a host-process emulator or its historical evidence.

## Executed validation results

All commands below ran in the assigned worktree (1,200-second command timeout):

- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed; 3,003 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — 74 passed in 2.73 s. Includes real middleware replica-selection
  counterexamples for both authenticated and unauthenticated identities;
  ASGI fixtures are not a deployed-production soak.
- `uv run python scripts/check-suite-inventory.py` — passed; all 15 suites,
  27,048 unique collected identities, no duplicate evidence.
- `uv run python scripts/check-doc-links.py` — passed; zero broken links.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — passed both with default provenance and the explicit supplied base.
- `uv run python -` imported the actual soak driver and evaluated retained
  `m3a-round6-shakedown.json`: failed checks were `sustain_duration` and
  `exact_rc_artifact`. Assertions for both failures and the current driver's
  negative artifact verdict passed. This validates rejection, not acceptance.

## Acceptance audit

| Issue criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:152-165` explicitly excludes concurrent users/Workspaces, Graph fan-out, successful tool/model work, Canvas and Goal/background-worker coverage. No approved complete RC workload was demonstrated. |
| Two application replicas | **UNVERIFIED for the RC**. `deploy/docker-compose.prod.yml:27-78` defines two services; the host-process driver does not exercise that artifact. A declared topology and two ASGI fixtures are not a deployment result. |
| Sustained saturation/reclaim/retry/leak/restart observations | **UNVERIFIED**. Re-evaluated historical evidence is 90.43 s, not the 14,400 s profile minimum. No new sustained run was executed. |
| No duplicate physical work, including schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED**. Existing probe tests validate admission receipts, not cross-replica physical effects. The profile documents the occurrence probe's cancellation without execution (`m3a-load-profile.md:197-200`). |
| Security/rate-limit/degraded non-bypass | **NOT MET** for replica-selection allowance. `test_replica_selection_has_an_independent_production_allowance` passes for both identity classes by observing `[200, 200, 429]` on each independent middleware instance. `maistro_server/main.py:628` installs this production middleware; `rate_limit.py:72-77` constructs its local state. Broader concurrent degraded/security behavior remains **UNVERIFIED**. |
| Complete telemetry with explicit thresholds | **UNVERIFIED**. The profile itself distinguishes driver-loop lag from application-loop lag and process-group counts from detached workers. Historical wrapper-only measurements cannot establish application RSS/FD health. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Historical process rejoin and terminal Run counts are not correlated physical Attempt recovery evidence; no fresh deployed failure injection was run. |
| Long soak of exact promoted RC/config | **NOT MET**. Executed evaluator rejects retained evidence for duration and artifact. Current `preflight_artifact_check()` is false with topology `host-uvicorn-preflight`. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED** as a complete acceptance claim. Existing evidence pack contains local classifications; this round found no new load result and made no prohibited external issue mutations. |
| Machine/human evidence bound to exact current artifact | **UNVERIFIED**. Historical JSON identifies `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD, and lacks the required exact production-image/config proof. This report records validation only, not a new soak. |

## Disposition / handoff

**BLOCKED** for #860 acceptance. Requested vulture repair was checked and had
no actionable findings. No code, test, inventory or quality-ledger change is
justified by that scan. Only this handoff document changed; no tests were added
or removed, so no inventory delta is required.

Next prerequisite: select the immutable RC artifact/runtime configuration and
complete its representative production-path workload/telemetry, resolve the
replica-selection contract mismatch through the canonical enforcement path,
then run at least four hours with physical Attempt fencing/recovery evidence.
A longer invocation of the current emulator would still fail the artifact gate;
no resources were spent presenting another short shakedown as progress.
No production acceptance gap was waived and no gate was weakened.

Progress: checked 1 assigned issue, done 0 acceptance-complete issues,
skipped 0, validation-command errors 0; next is the blocked RC soak work above.
The report is committed locally; no push, PR, merge or GitHub mutation occurred.
