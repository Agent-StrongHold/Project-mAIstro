# Issue #860 — repair checkpoint (88db350f)

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `f5463247e19f1e67665dd52ea27149eabb22604e`.
- Assigned base: `7334621bf797178dd992622d55aaead33bf9d094`.
- Initial worktree is clean; no incoming edits require salvage.
- Input snapshot: job `88db350fad444d62be58d648aaa6f5e6` dispatch-context.json and prior job `9705deb97ba0441a960aedfde8d881e9/result.json`.
- Frozen inspection scope: repository instructions, relevant ADRs, production rate-limit wiring, soak driver/evaluator and adjacent tests, retained soak evidence, vulture gate/ledger and its actual reported source identities.
- Planned edit scope: this report; only evidence-backed vulture source/ledger repairs if the exact scan identifies any. Test additions, if needed, require an inventory note.

## Initial evidence / assumptions

The job directory contains no driver `check-*.log` files. Validation must run locally. The prior result is BLOCKED, not proof of current behavior. The profile explicitly describes host-uvicorn preflight rather than the production Compose artifact. A green static gate cannot satisfy production promotion acceptance. Treat this as a writer/CI-repair assignment, not permission to introduce a new scheduler or waive soak criteria. No remote mutations or ref refreshes are needed.

## Progress

Exact mandated vulture scan completed successfully: 1,336 findings match 1,336 reviewed identities, zero unclassified/never-allowlist findings. No source deletion or ledger amendment is warranted. The gate reports its own baseline `56332162cf63` and candidate `f5463247e19f`; this is distinct from the assigned comparison base. Read the issue's ten acceptance criteria from the frozen dispatch. Existing regression tests exercise real middleware instances and explicitly reproduce independent replica allowances. Focused validation completed: `uv run ruff check .` passed; `uv run ruff format --check .` passed (3,003 files); `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` passed (74 tests); `git diff --check 7334621bf797178dd992622d55aaead33bf9d094` passed. Importing the current evaluator and evaluating retained `m3a-round6-shakedown.json` returned failed gates `sustain_duration` and `exact_rc_artifact`; observed duration is 90.43 seconds against 14,400 required. The old whitespace finding does not reproduce against the assigned base.

Reviewed ADR-081 (Proposed, not an accepted override), ADR-085 (Accepted, per-principal rate limiting), ADR-081426-1f7c (Accepted, runtime mechanics use Attempt identity), ADR-081626-f383 (Accepted, canonical-store execution fencing), and ADR-082426-82c7 (Accepted, occurrence uniqueness is Run-store admission, not physical execution). Reconciliation: admission uniqueness cannot establish physical-work uniqueness; per-replica enforcement cannot establish a cluster-wide principal allowance. No alternate scheduler, store, auth path, or acceptance waiver introduced.

## Acceptance audit (all ten issue criteria)

| Criterion | Current evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:152-164` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model work, Design/Canvas and Goal/background-worker coverage. Production Compose requires a reachable model gateway (`deploy/docker-compose.prod.yml:46-58`); degraded provider-less preflight is not equivalent. |
| At least two supported production replicas | UNVERIFIED for the RC. Compose declares two application services (`deploy/docker-compose.prod.yml:26-76`), but the driver boots host processes. ASGI middleware tests are not a production deployment. |
| Sustained saturation, reclaim, retry and leak observation | UNVERIFIED. Executed current evaluator rejects the retained 90.43-second run against the 14,400-second minimum (`evidence/m3a-round6-shakedown.json:221-225`). |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED. Retained schedule probe cancels its queued Run (`evidence/m3a-round6-shakedown.json:11-15`); one admitted Run is not physical Attempt/Goal recovery evidence. Existing tests verify admission probe semantics, not production cross-replica physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Counterexample reproduced by both parameter cases of `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439-488`): each replica accepts two requests for the same identity after the first replica's allowance is exhausted. The middleware is production-wired (`packages/maistro-server/src/maistro_server/main.py:628`), and creates an independent in-memory limiter (`api/rate_limit.py:72-76`). Broader production security/degraded acceptance remains UNVERIFIED. |
| Complete application telemetry with thresholds | UNVERIFIED. Existing real-process sampler regression passes, but no new production soak validates it. Historical wrapper-only RSS/FD observations and driver-loop lag cannot establish application-loop latency, worker health, pool saturation or leak behavior (`m3a-load-profile.md:156-164`). |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. Historical exit/rejoin and terminal Run counts do not identify or fence physical Attempts during recovery; no new active-work production restart was run. |
| Long soak of exact RC artifact/configuration | UNVERIFIED / blocked. Current `preflight_artifact_check` always rejects its host topology (`scripts/soak/run_soak.py:635-646`); evaluator execution rejects retained evidence for both artifact and duration. Extending this driver to four hours would not satisfy acceptance. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completeness. Historical evidence pack records findings; no new load run or external filing/closure was performed. No GitHub mutation is permitted in this lane. |
| Machine/human evidence bound to exact promoted artifact | UNVERIFIED. Historical JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c` (`evidence/m3a-round6-shakedown.json:70`), not the assigned HEAD, and lacks application-image identity. A historical evidence pack is not current RC evidence. |

## Final validation / handoff

Additional workflow prerequisite gates executed successfully:

- `uv run python scripts/check-ratchet-provenance.py`: passed (49 quality JSON consumers have explicit provenance; delegated gates passed).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed for tracked changes. Post-commit `git show --format= --check HEAD` caught a trailing blank line in this new report (not scanned while untracked); removed before final handoff and rechecked.
- Assigned base commit resolves locally; no fetch/merge was needed.

Changed file: this report only. No production code, ledger, grant, tests or inventory count changed; no inventory note is required. Existing meaningful tests were executed rather than duplicated. No production soak was run, no new runtime evidence is claimed, and no gate was weakened. The exact CI repair target is already green at the assigned HEAD.

Disposition: BLOCKED on production acceptance, not on vulture. Next work requires a pinned production RC deployment/configuration and representative production-path workloads, a resolution of the replica-selection allowance requirement, and a new artifact-bound long soak with physical Attempt fencing/recovery and complete application telemetry. Repeating the same static repair or extending the host emulator cannot discharge these blockers.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0; outstanding validation errors 0. Preserve all prior evidence and hand off this committed report; do not promote or close #860.
