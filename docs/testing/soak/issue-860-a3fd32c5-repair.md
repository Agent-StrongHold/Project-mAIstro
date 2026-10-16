# Issue #860 repair checkpoint — a3fd32c5

## Frozen scope

- Assigned issue: #860 only; no GitHub mutations or PR processing.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `0182370753c741cb240860471d803d2b8dd6066f`; initially clean.
- Supplied base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Repair file snapshot: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, `quality/vulture-baseline.json` (only if actual scan requires reviewed identity changes), this report, and `docs/testing/inventory-notes/860-a3fd32c5-schema-fence.md`.
- Inspect production schema implementation, adjacent tests, soak harness/tests, quality gate implementation/workflow, and relevant ADRs read-only.

## Initial evidence and assumptions

The supplied previous `check-3.log` fails the schema-fence test: 24 DDL calls versus 21 expected. Reproduce before repairing; do not drop production schema upgrades to satisfy an obsolete test. The previous result is BLOCKED on missing exact-RC production soak, not a merge conflict. No develop merge is warranted by that evidence.

No `check-*.log` files were present in this job directory at initial inspection. The referenced previous check log and result artifact were read. Dispatch issue acceptance has ten criteria; deterministic validation cannot establish deployment/long-soak completion.

## Reproduction results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. The historical failure does not reproduce: the current test already independently lists the three Gauntlet columns at lines 173–175. No test or production edit is warranted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1322 findings / 1322 reviewed identities, zero unclassified and never-allowlist findings. No identities require amendment. The auto-resolved baseline was `321cbdb8fe9b`; explicit supplied-base provenance will also be checked.
- Supplied develop base resolves locally. No unresolved refs or uncommitted incoming work.
- `docs/testing/soak/README.md` does not exist; skipped. No alternate README is assumed.

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/Run/NodeRun/Attempt ownership) and ADR-081626-f383 (durable Attempt lease fencing). The latter explicitly does not itself establish expiry takeover: the issue's reclaim criterion requires observed evidence, not an inferred claim from token fencing. The Gauntlet document ADR-100126-8c2d is Proposed, not accepted authority. No scheduling, authorization, schema, or event authority changes are made.

## Additional executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**. Includes exact-RC rejection at CLI exit, real production middleware replica-selection probes, and production task-router receipt probes.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed; trusted merge base remains `321cbdb8fe9b`, 1322/1322 identities. This is the gate's provenance calculation, not a comparison against candidate-edited debt.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 53 quality JSON consumers; delegated checks passed. Non-fatal invalid-escape SyntaxWarnings were emitted.

## Reproduced acceptance limitations

- `scripts/soak/run_soak.py:744` (`preflight_artifact_check`) always returns `ok: False`, correctly refusing to call host uvicorn the promoted Compose artifact. The three parametrized four-hour CLI tests execute this rejection.
- `tests/test_soak_promotion_gates.py:439`: real production `RateLimitMiddleware` gives the same authenticated/unauthenticated identity `[200, 200, 429]` independently on each replica. Passing local enforcement tests cannot prove a shared cluster allowance. These ASGI tests do not establish deployed ingress reachability/security.
- `tests/test_soak_promotion_gates.py:564`: real task router with two queues sharing the canonical admission spine yields owner HTTP 200 and peer HTTP 404 for the observed receipt. This is not a deployed soak or physical-work duplication proof.
- No new tests or suite-count changes; no inventory delta note is needed. No ledger changes are justified by the executed scan.

## Acceptance disposition (all ten issue criteria)

| Criterion | Current evidence / disposition |
|---|---|
| Representative RC workload | **UNVERIFIED**. Read `m3a-load-profile.md`: one API key, no concurrent Workspace population, successful model/tool calls, Graph fan-out, or Design/Canvas coverage. The document explicitly retains these gaps; no waiver inferred. |
| At least two deployed application replicas | **UNVERIFIED** for this candidate. Two ASGI instances in executed tests are not deployment evidence; historical reports are not rerun results. |
| Sustained saturation, queues, reclaim, retries, leaks | **UNVERIFIED**. No long live load executed in this round. Schema unit tests and admission accounting tests do not establish these observations. |
| No duplicate physical work | **UNVERIFIED**. Harness admission identity checks do not execute/correlate physical work for the schedule race; the profile explicitly states the queued probe Run is cancelled. |
| Replica-resistant security/rate/degraded behavior | **UNVERIFIED** as a production claim; independent rate allowances are positively reproduced in production middleware tests. No alternate authorization/rate-limit authority introduced. |
| Complete telemetry with pass/fail thresholds | **UNVERIFIED**. Inspected profile/harness: dedicated driver PostgreSQL probe and driver loop lag are not application query/loop latency; process-group measurements exclude detached workers. No new production telemetry captured. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED**. Existing process-group sampler test passes, but it is not recovery of in-flight canonical Attempts. |
| Long soak of exact RC artifact/config | **UNVERIFIED / BLOCKED**. Executed CLI regression tests prove host preflight cannot pass exact-RC gate, even with synthetic four-hour evidence. No immutable promoted image/configuration was supplied for a new production run. |
| Findings classified/filed to earliest invariant | **UNVERIFIED** for complete issue acceptance. Existing evidence pack documents historical findings, but filing completeness was not independently established. No GitHub mutations permitted or performed. |
| Machine/human evidence bound to exact hashes | **UNVERIFIED** for promotion. This report binds deterministic checks to the starting HEAD, not a deployed image/configuration. Historical hash-bound packs do not establish current-candidate RC acceptance. |

## Final handoff

Verdict: **BLOCKED**, not integration approval. The supplied historical test failure is already repaired at the starting HEAD, and no vulture identity mismatch exists. Do not make cosmetic source edits or alter a clean debt ledger to manufacture a repair.

Only changed file: `docs/testing/soak/issue-860-a3fd32c5-repair.md` (this validation handoff). No production, test, inventory, baseline, or grant edits. `git diff --check` passed before finalization. Supplied base and HEAD have verified merge base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.

Next: provide the immutable RC deployment/configuration, complete representative workload/telemetry and physical-Attempt recovery coverage, resolve the replica allowance contract at its existing authority, then run and publish a fresh ≥4-hour production soak. A host preflight extension or another repetition of these green unit checks cannot discharge that blocker.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production acceptance evidence}. One assigned issue checked; acceptance remains blocked. Commit this handoff locally and leave the worktree clean; no push.

