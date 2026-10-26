# Issue #860 — job 852d6440 validation

## Frozen scope and initial observations

Only issue #860 at `39d44f01e903c1a6817bdbc528361d4b30837573`, against supplied base `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Worktree initially clean. Writer role follows explicit repair assignment; no GitHub mutations or remote refreshes.

Inspect supplied dispatch issue body, prior result and failed log, repository instructions, applicable execution/fencing/deployment ADRs, soak profile/harness and adjacent tests. Candidate edits limited to this report and evidence-justified repairs in `quality/vulture-baseline.json`, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `packages/maistro-core/tests/persistence/test_pg_learnings.py`, and a corresponding inventory note if tests change. No other issues or historical report collection will be processed.

Current job directory has no check-*.log files. Supplied historical check-3.log actually reports a learning-schema fence assertion (24 statements versus 21), not a vulture failure. Prior result reports BLOCKED for missing exact-RC soak and replica-local enforcement/receipt visibility. These are hypotheses pending fresh validation, not accepted verification claims.

## Fresh validation results

Commands executed in the assigned worktree with 1,200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,322 reviewed identities / 1,322 findings, zero unclassified or never-allowlist. No ledger repair indicated.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. The supplied historical assertion failure does not reproduce. Skips are not live PostgreSQL evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 73 passed.

Read the exact issue body from the supplied immutable dispatch and current profile. The latter explicitly limits this harness to host-process preflight, not the promoted Compose image. Profile admits missing multi-user/Workspace, fan-out, successful tool/model, Design/Canvas, Goal reconciliation, application-loop and physical-work recovery evidence. No tests changed; no inventory delta.

## Architecture and acceptance evidence

Read repository instructions and the documentation authority map. Accepted ADR-081426-1f7c confines ExecutionRuntime to physical execution mechanics with canonical Attempt identity; accepted ADR-081626-f383 reserves durable fencing authority to the Run store and explicitly leaves live-Attempt expiry takeover undefined. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; a soak cannot invent reclaim authority. The profile's deployment ADR-081 is Proposed, not an accepted override of those boundaries.

Source inspection confirms the historical schema failure is already repaired: the independent expectation at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176` includes three validation audit columns, and production upgrades remain inside the advisory transaction fence at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`. The vulture command matches `.github/workflows/vulture-ratchet.yml:82`; editing an already exact ledger would not repair anything.

| Issue acceptance criterion | Current executed evidence / limitation |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md` documents omissions; no selected RC applicability assessment for users/Workspaces, fan-out, successful tool/model calls, Canvas or background reconciliation. |
| At least two deployed application replicas | **UNVERIFIED**. Fresh tests instantiate two ASGI apps, not deployed production replicas. |
| Sustained saturation, growth, reclaim, retries and leaks | **UNVERIFIED**. No sustained production traffic run this round; lease-reclaim semantics also need the accepted-contract resolution above. |
| Schedule/task/Run/Attempt uniqueness and Goal reconciliation | **UNVERIFIED**. Passing probe tests and canonical admission backpressure tests are not physical-work uniqueness or sustained reconciliation evidence. |
| Replica-resistant rate/security/degraded behavior | **UNVERIFIED** overall, with contrary local-budget evidence: executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both production middleware instances for the same authenticated/unauthenticated identity. Production explicitly documents process-local enforcement at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`. Backpressure test passes but does not prove cluster-wide security. |
| Production telemetry and thresholds | **UNVERIFIED**. Sampler/evaluator tests pass; no fresh production PostgreSQL, application-loop, worker, queue, latency/error or long-window leak series. |
| Active-work kill/restart, drain, fencing/recovery | **UNVERIFIED**. Cleanup and gate tests are not active-work recovery experiments. The executed production-router probe at `tests/test_soak_promotion_gates.py:564` observes local receipt 200 and peer 404, consistent with `packages/maistro-server/src/maistro_server/api/tasks.py:144`. |
| Long soak of exact promoted artifact/configuration | **UNVERIFIED**. `scripts/soak/run_soak.py:744` explicitly rejects exact-artifact equivalence. Executed CLI tests at `tests/test_soak_promotion_gates.py:104` reject missing/null/preflight artifact checks even with synthetic four-hour duration. No immutable RC image/effective configuration is designated by this dispatch. |
| Findings classified to earliest broken milestone | **UNVERIFIED** for completeness. No new load experiment or filing performed; historical classifications are not fresh production evidence. GitHub mutations prohibited. |
| Machine/human evidence tied to hashes | **UNVERIFIED** at promotion grade. This report ties focused validation to the supplied source head, not a promoted image/configuration or new soak. |

## Disposition and handoff

**BLOCKED**. Neither the historical schema assertion failure nor any unbanked vulture identity reproduces. No source, test, ledger or gate modification is warranted. Only this report changes; existing work remains intact.

Next action is not another identical CI-repair round. Designate the immutable RC image and effective configuration, resolve the replica allowance/receipt and reclaim-contract constraints, and supply a production-artifact workload/telemetry runner covering the missing acceptance surfaces. Then execute the representative >=4-hour profile with active physical work and recovery, recording artifact/configuration hashes. Do not extend the host emulator and relabel it production proof.

Progress: checked 1 issue; done 0 full acceptance sets; skipped 0 issues; errors 0 fresh validation commands. All ten acceptance criteria remain unproven at production grade. No merge conflict, remote refresh, new tests, inventory/ledger edits or GitHub mutations. Final whitespace check and local commit follow.
