# Issue #57 repair — frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD: `5655177c64289d169164d3dc945ca0c030cff8f9`; supplied develop base: `c2d7209f1dbc1039e8ca9d99444b88ded3bbe26b`.
- Frozen item list: issue #57 only; inspect supplied dispatch-context.json and prior result; reproduce exact vulture debt gate and relevant #57 acceptance tests; repair actual findings only. No GitHub actions or scope expansion.
- Initial status clean. No incoming changes require salvage.
- Job directory contains no `check-*.log` files at initial inspection; driver validation evidence is unavailable, so execute relevant checks locally.
- Prior result records external dependency #847 open and inherited unreachable admission_identity module; these claims require checking, not assumption.
- File scope: existing #57 governed tool paths/tests/docs, exact vulture ledger (explicitly permitted), this repair note. Expand only for an actual reproduced failure relevant to the lane; record it here.
- Ambiguity: supplied develop diff includes unrelated inherited deletions. Do not attempt an unsolicited develop synchronization (no sync conflict is reported); retain all inherited work.

## Results

- Supplied issue body independently read: 12 acceptance criteria. Frozen #847 is open; criterion 12 cannot be satisfied locally. No remote refresh performed.
- `uv sync --locked --extra dev` passed.
- Exact requested vulture gate passed at starting HEAD: 1322 findings, zero unclassified, zero never_allowlist; trusted base e20e9f52ea94, 1326 reviewed identities. No unbanked identities reproduced, so no ledger amendment is justified.
- SECURITY.md:35 already states the registry is constructed by governed contracts and separates that from Sentinel approval-gating limitations. Prior documentation drift is not reproducible; no rewrite warranted.
- Repository lint and format checks passed (3368 files).
- Focused core tests passed: 1571 passed, 11 skipped, one unawaited mock coroutine warning (`repair-core.log`). Includes tools/capabilities, Agent allowlist/strategy/spec/audit paths, PM-fleet retirement.
- ADR-050-tool-reversibility.md and ADR-073-expected-effects.md: not found; skipped. Resolved actual filenames with local file search before further reading.
- Bootstrap: 236 passed, 7 skipped; Hive boot/chat/legacy adapter wiring: 86 passed; adversarial raw-effect/model-egress gate tests: 74 passed. Logs are `repair-bootstrap.log`, `repair-hive.log`, `repair-adversarial-gates.log` in the assigned job directory.
- Gates run with supplied `RATCHET_BASE_REV=c2d7209f...` resolve trusted merge base e20e9f52ea94. Exact vulture passed again. Model-egress (also runs direct-effect inventory), convergence matrix, security inventory, reachability dispositions passed.
- `check-reachability.py` and `check-ratchet-provenance.py` reproduce the inherited failure: `maistro.runs.admission_identity` is unreachable and absent from candidate baseline. Do not invent callers or edit forbidden reachability ledgers.
- `scripts/check-direct-effects.py`: not found; skipped (command exited 2). Direct-effect inventory actually executed inside `check-model-egress.py`: 51 matched sites, four TOOL_EFFECT entries. No independent missing script is claimed as passing.
- Read ADR-050 and ADR-073 using resolved filenames; accepted ADR-004 amendment removes misleading unused AgentSpec security fields. SECURITY.md appropriately does not claim complete ADR-050/Sentinel integration.
- Exact repository mypy command passed (908 source files; `repair-mypy.log`). Three-suite inventory passed: core 16798, bootstrap 243, Hive backend 3801; 20842 unique test identities, zero copied duplicates (`repair-inventory.log`). No test additions/count changes this round; no inventory-delta note needed.
- Actual Docker image inspection fails: `No such image: maistro-builders:latest` (`repair-builder-image.log`); live container execution remains UNVERIFIED, not inferred from unit tests.
- Frozen PR #506 patch independently enumerates seven original TOOL_EFFECT sites (two chat, two graph_runner, two BrowserClient implementation, one pm_runner). Current PM-fleet retirement tests (included in 1571) assert pm_runner and its obsolete adapters absent. Legacy graph sites remain under `_run_tool_node`'s canonical Invocation, but do NOT consume ToolContractRegistry schema/reversibility/expected-effect controls; full criterion 10 equivalence remains UNVERIFIED.
- Frozen #55 source is also open. Criterion 1 is verified only for reachable tool composition consuming the production Invocation API, not remote M1 issue closure or zero repository-wide bypass debt. Model-egress reports 12 existing reachable escapes assigned to #56.
- `admission_identity.py` differs from supplied develop tip c2d7209f only in its inactive-leaf docstring; public exports/publication tests also differ in the inherited branch. Do not repeat prior claim that this HEAD equals the current supplied develop tip. This round did not introduce the failure. Unsolicited admission-publication recovery/develop merge would exceed the frozen #57/Vulture scope; leave an explicit integrator handoff.
- Read accepted ADR-004 amendment and production ToolContractRegistry / GovernedToolExecutor / Hive wiring. Tool calls use the existing Binding -> Invocation boundary; no execution authority is introduced by this round.
- `git diff --check` passed. Only this repair note is changed. No source, test, inventory, ledger or grant edits were warranted by the requested exact-debt check.

## Acceptance evidence (this round only)

All logs below are in `/home/dev/maistro/jobs/ce7093c2d72e4a47962a3e088093f3b6/`.

1. **Consume #55 seam, not second executor:** production `contracts.py::_invoke_admitted` calls existing `effects.invocations.invoke`; Hive uses the live Container and persisted execution records. Real SQLite Container boot/chat tool tests passed in `repair-hive.log` (86 tests). Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains authoritative. #55 closure and completion of repository-wide M1 migration are **UNVERIFIED** (frozen #55 is open).
2. **Authorization plus required predictions:** `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passed in `repair-core.log`; canonical Invocation admission/policy tests passed in the same run. Evidence is attached before dispatch. Shipped Hive contracts are read-only; production high-impact host configuration outside this registry is **UNVERIFIED**.
3. **Effective Agent tool set:** Agent shared callback gate (`base.py:876`), ReAct/artificer unlisted-tool denial, strategy callback refusal, BuildersLearning retirement and Hive caller-narrowing tests passed. Host Binding/policy remain necessary; declarations cannot grant them.
4. **Missing/unknown schemas:** `test_agent_allowlist_and_unknown_schema_fail_before_backend`, ReAct/artificer unknown-schema tests and Hive malformed/extra-field refusal tests passed, with backend-not-called assertions. Validator implements a JSON Schema subset; arbitrary unsupported schema keywords are **UNVERIFIED**, not claimed fully supported.
5. **Structured commands across backends:** full bootstrap suite passed (236); argv schema/raw-cmd/metacharacter refusal tests and local/container backend hardening tests executed. Live container backend remains **UNVERIFIED**: image absent, integration cases skipped. Windows-only escape case also skipped.
6. **Host reversibility:** registry validation tests and Hive recorded Invocation-tier test passed; production executor resolves tier from ToolContractRegistry, and canonical policy enforces an irreversible approval floor. This does not prove all ADR-050 compensator/Sentinel integration; SECURITY.md states that limitation.
7. **Exact recomputable evidence:** both SQLite reopen cases passed in `test_mismatch_event_recovers_after_sqlite_reopen`, asserting capability/provider, materialized arguments/digest, pre-state digest, expected/observed post-state, Invocation/execution identity, stable evidence digest and policy version. PostgreSQL restart validation **UNVERIFIED** (PG tests skipped).
8. **Durable mismatch, host verdict:** mismatch-not-success and interrupted-append tests passed (failure before commit and lost acknowledgement after commit). Reopening/replaying gives one backend dispatch, one durable correlated mismatch event and immutable first observation. Recovery requires replay; autonomous repair is not established.
9. **Required high-impact prediction:** `test_high_impact_contract_without_expected_effect_fails_closed` passed; incomplete configured contract refuses at registration before effects.
10. **Seven TOOL_EFFECT entries:** original seven verified from supplied PR #506 patch. Two chat wrappers route through governed helpers (routing and real tool tests); graph_runner wrappers now live in legacy_dag_node under canonical Invocation (legacy tests); BrowserClient sites are provider implementations (inventory matches); pm_runner is absent (executed PM retirement tests). Full applicable #57 control equivalence for legacy tool_config is **UNVERIFIED**: legacy admission does not use ToolContractRegistry.
11. **Reject raw/direct bypass:** 74 adversarial direct-effect/model-egress gate tests passed, including injected raw Hive dispatcher/browser paths; `check-model-egress.py` passed the direct-effect inventory (51 sites). Existing model-egress escape debt is not silently counted as migrated.
12. **#847 closes first:** **UNMET** in frozen dispatch snapshot: issue state is open. Adversarial tests cannot satisfy an issue-closure prerequisite; no GitHub mutation attempted.

## Final handoff

**BLOCKED**. The requested Vulture failure is not reproducible, and prior SECURITY.md drift is already corrected. Do not make cosmetic changes or bank guessed identities. Two actual required gates fail on inherited inactive admission_identity publication; only the Vulture ledger is writable in this lane, so neither forbidden ledger edits nor fake callers are a valid repair. An integrator must reconcile the branch's admission publication with develop separately. #847 sequencing is also still unmet.

Changed file: this note only. No new tests, so no inventory delta is required; the existing three-suite inventory was validated. Commands/results are recorded above and in the job logs. Residual risks: live container and PostgreSQL execution, arbitrary JSON Schema support, legacy tool-specific control equivalence, remote CI, and #55/#847 completion remain unverified/unmet. One mock-coroutine warning remains in core tests.

Progress: checked 1 assigned issue, done 1 focused validation/handoff, skipped 0 assigned issues, errors 2 inherited required-gate failures (same module). One attempted nonexistent direct-effect script also exited 2; its inventory check was actually executed by the model-egress gate. Next: integrator addresses inherited admission publication and external prerequisite sequencing; verifier reviews the committed evidence. No push/PR/merge/comment/closure actions.

