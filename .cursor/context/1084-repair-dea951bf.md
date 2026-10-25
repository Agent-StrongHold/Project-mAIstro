# #1084 repair checkpoint (job dea951bf)

## Frozen scope
- Only issue #1084, branch `auto-1084`, assigned worktree `/home/dev/Git/wt/auto-1084`.
- Starting HEAD `565dd3d8939c7ab842ff67f8235f9ed8906f2291`; supplied develop `2014ab888c0bff4541a10cc2a808e021e95cb404` resolves and equals local origin/develop at inspection.
- Snapshot sources: supplied dispatch-context.json and check-0.log through check-7.log; no GitHub enumeration/mutation.
- Repair targets: reproduce Quality/Pyright and exact-debt-ledger vulture; resolve develop-sync if present; correct contradictory lane notes based on evidence. Validate existing #1084 egress tests and gates; change production/tests only for reproduced failures. Relevant files frozen to existing #1084 production/tests in `git diff --name-only <supplied-base>..HEAD`, quality/vulture-baseline.json (explicit exception), and these lane notes. Develop merge may introduce upstream files only.
- Initial status clean; no uncommitted salvage required, no merge conflict present.

## Ambiguities and assumptions
- Prompt has generic verifier and writer instructions; assigned lane is repair/writer, so local edits and commit are required.
- Prior closure-keyword finding concerns inherited commit messages. After reproducing the exact nine messages, treat the assigned repair of that supplied blocker as authorizing a bounded local message-only rebuild. Preserve the entire pre-repair graph under a local backup ref, preserve trees/metadata and develop-side ancestry, and atomically update the lane ref only with a clean worktree and identical final tree. No integration, push, branch deletion, or work discard.
- Fetch/merge instruction is conditional on preserved sync conflict. Initial tree is clean, but origin/develop is newer than lane head; inspect ancestry then synchronize the resolved supplied develop ref without re-enumerating GitHub.

## Progress
- Initially read repository AGENTS.md and supplied dispatch issue body; the independent criterion-by-criterion assessment is below.
- Existing lane notes contradict themselves on inherited auto-close commit text; prior assertions are not verification evidence.
- Read driver check-0..7 logs: dependency sync, ruff, focused tests (290 + 153), three suite inventories all passed at the starting head. Read previous result artifact; the only previous verifier block was commit-message auto-close text.
- Read accepted ADR-081226-6b46 (Binding/Provider/Invocation), ADR-081426-1f7c (Attempt execution mechanics) and ADR-083026-1cb1 (correlation descriptive, not authorization), plus SPEC-285 observer seam. No alternate runtime/authorization path is permitted.
- Synchronized the exact supplied develop ref via true merge `b1f6709ed5f4`; no conflicts occurred. No remote re-enumeration was needed. Upstream-only quality ledger changes were inherited, not hand-edited.
- CI-exact Pyright replay after `uv sync --locked --all-extras`, editable maistro-evolve, pyright 1.1.414: 827 files, 11 errors/54 warnings, baseline 21, checker exit 0. Diagnostics: `/tmp/1084-dea951bf-pyright.json`. The named failure does not reproduce; no guessed production/type fixes.
- Exact vulture command after merge: 1297 findings == 1297 reviewed identities, base 2014ab888c0b, exit 0. No ledger edits warranted.
- Initial commit-message scan against the frozen develop base reproduced nine branch-unique keyword-bearing commits (including 61f22af235f1, e9aad735626d, c44240217fe1); the old blanket claim was false. The subsequent bounded repair is recorded below.
- Production review considered whether GovernedModelChatClient._call could overwrite an operator-disabled Binding. Store inspection resolves this: all Binding stores reject changed definitions and retain revocation tombstones. No reproduced overwrite; no speculative production repair. The current route tests compose real Container services but not real embedded startup, and only the adapter test checks Invocation rows; this is not full same-request acceptance proof.
- Message repair snapshot is exactly the nine reproduced branch-only commits from the frozen supplied develop range: 61f22af235f1, e9aad735626d, 4fd6dafb8a9a, c44240217fe1, 58631e60a677, 0ab0bb698d63, 6124afb907d6, 7c5c6c9a3c31, 43731c7984d0. Replace closure verb with `Refs`, retaining issue references and all other text. Descendant parent hashes necessarily change; no file content or develop ancestor is rewritten.
- First rebuild safely stopped before updating HEAD because a changed commit carried a signature. Backup `refs/heads/auto-1084-before-message-repair-dea951bf` preserves the exact original tip `9a1a92ee8` and its signatures. Rebuilt commits cannot retain valid signatures over different parents/messages: detach signature headers only on rebuilt objects, preserve originals in the backup, and record affected identities. Author/committer timestamps and trees remain unchanged. No worktree edits were discarded.
- Message repair completed at `93ef338be67b45c1ec93fa343df6df09d46bbc09`: nine messages reworded; 115 descendant objects rebuilt. Every old/new commit tree checked identical; supplied develop remains exact merge-base. Final input (including notes) preserved at `refs/heads/auto-1084-message-repair-input-dea951bf` (`ffa9443a9`). Exact mapping and detached signature identities: `/tmp/1084-dea951bf-message-repair.json`. A full branch-only scan finds zero closure-keyword matches. No history was pushed.
- After sync/rebuild: full Hive backend `uv run pytest packages/hive-conductor/backend/tests -x -q` -> 4043 passed, 26 skipped (200s); focused core/server command -> 290 passed, 11 skipped. Logs `/tmp/1084-dea951bf-{hive,core-server}.log`.
- Post-rebuild gates: ruff check and format-check pass (3500 files); check-model-egress (16 physical callers, unrelated deferred escapes remain), check-design-model-egress, check_direct_effects (51 sites), check-promotion-surface, check-reachability (1462 modules /148 ledgered unreachable), check-radon-baseline (127 ==127) all exit 0.
- Inventory after sync: Hive 4069, core 17931, server 657, all match recorded notes; no tests were added/removed in this round. Vulture re-run still 1297 ==1297. `check-ratchet-provenance.py` exits 0 (54 consumers).
- Additional read-only acceptance probe FAILED: `PYTHONPATH=/tmp uv run pytest -p maistro1084_acceptance_probe packages/hive-conductor/backend/tests/test_chat_run_admission.py::test_repeated_complete_turns_share_the_workspace_agent_under_distinct_runs -x -q -s` (plugin `/tmp/maistro1084_acceptance_probe.py`, log `/tmp/1084-dea951bf-acceptance-join.log`). Two real route calls each return 200, but the Invocation's workspace is `default` while its persisted Run belongs to `052e73a7c224`; Invocation actor is also empty while Run actor is `user`. The existing green test checks Runs/Attempts but not their Invocation joins. No admission, policy or usage success was mocked by the probe; it only reads rows after the existing real route test. This prevents MERGE-READY regardless of repaired CI/history.

## Acceptance assessment / unresolved handoff

The named CI/history/sync repairs are complete. Parent issue readiness is **NEEDS-REPAIR**, not integration approval. Do not repair this by copying ambient strings into authorization fields or adding a permissive default Binding. The accepted ADRs require persisted execution and configured scope authority; `AdmittedModelCalls` already implements that validation for other consumers. Converging the remaining compatibility consumers onto it, preserving the streaming observer, needs a focused production/test repair beyond this gate/history round. This round deliberately leaves production unchanged rather than guessing at new grants or credential scope.

| Issue acceptance criterion | Executed evidence and limits |
| --- | --- |
| /chat/complete, /chat/stream, voice have Invocation before dispatch | Full Hive suite passes real route admission/lifecycle cases; core streaming test observes a RUNNING Invocation. The extra complete-route join assertion FAILS. Matching before-dispatch evidence for all three real-startup doors remains UNVERIFIED. |
| Boot and later-materialized Agents share authorized authority | Full Hive suite passes structural bridge/materialization tests; core composition suite passes. The bridge tests substitute Container/roster construction; actual boot-to-later-materialized authorized dispatch joins remain UNVERIFIED. |
| Real run_task callers use persisted identities | Focused core/server tests pass, including bound-context propagation. But `conductor.py:176-191` still synthesizes identities when no context exists; `test_conductor.py:983` explicitly expects that behavior. All actual caller persistence/fail-closed claims remain UNVERIFIED; prior blanket claim was too strong. |
| model/messages/tools/tool_choice/response-format/timeout/retry/circuit remain truthful | Focused core egress/tool_choice/conductor suites pass; Hive adapter suite passes. Whole production-consumer parity remains UNVERIFIED (conversation-only shaping intentionally drops extra fields). Sibling tool_choice/identity ownership not altered. |
| Incremental streaming, cancellation/failure/usage | SPEC-285 core observer tests and Hive port tests pass within the 290/4043 runs. Shipped `routes/chat.py:275-324` intentionally remains single-done M0 containment, not incremental route delivery; route-level incremental acceptance remains UNVERIFIED and needs owner reconciliation rather than assuming the port proof covers it. |
| Binding-constrained selection/fallback; failed Invocation cannot succeed | Core pin/fallback/refusal/dedup tests and Hive model-failure tests pass. Full configured chat/Agent authorization behavior remains UNVERIFIED. |
| Missing actor/admission/config, foreign/disabled/revoked Binding, credential/policy/quota refusal => zero effects | Real route admission/config refusals pass; core credential/policy/quota tests pass. Probe shows the successful chat Invocation drops the authenticated actor and scopes to default; full consumer refusal matrix remains UNVERIFIED, not inferred from isolated authorities. |
| Configured startup same-request actor/Workspace Agent/Run/NodeRun/Attempt/Binding/Provider/Invocation/security/usage join | FAILED on real complete-route join in an embedded Container: Run Workspace `052e73a7c224` vs Invocation `default`, Run actor `user` vs Invocation empty. Full startup request additionally remains UNVERIFIED: fixture binds Container into an engine port rather than executing embedded bridge startup. |
| Only final provider transport substituted; no private authority/success mocks | Failing join probe reuses real Container/admission/policy/usage and only reads rows; gateway transport alone is substituted on that route. Existing bridge/vision unit tests use broader mocks and cannot prove the complete acceptance contract. Full-startup proof remains UNVERIFIED. |
| Physical inventory removals only; unrelated ownership visible | Executed check-model-egress and check_direct_effects pass: 16 physical callers, 51 dispositioned sites; deferred non-lane escapes remain visible. All three changed-package inventories match. |

### Concrete evidence / next repair

- `packages/hive-conductor/backend/services/chat_completion.py:126-149` rebuilds the conversation-only request without Workspace scope.
- `packages/hive-conductor/backend/adapters/llm_http.py:140` passes the resulting blank Workspace metadata; `model_chat.py:605-615` merges it over ambient values, then `:640-659` falls back to the deployment/default Binding scope.
- `packages/maistro-core/src/maistro/capabilities/model_chat.py:708-717` calls egress without an actor; the default is empty. The probe reads the resulting empty persisted actor, not a mocked policy outcome.
- Preserve the canonical validated actor, admitted Workspace/Project and configured Binding permission ceiling; do not merely carry caller-provided scope through `conversation_only`.
- PostgreSQL/live-provider/installed-profile proofs were not run this round (11 focused/26 Hive skips are not passes). Existing #1824/#87 boundaries remain separate.

### Reproduce the additional read-only acceptance failure

Save this diagnostic hook as `/tmp/maistro1084_acceptance_probe.py`, then run:
`PYTHONPATH=/tmp uv run pytest -p maistro1084_acceptance_probe packages/hive-conductor/backend/tests/test_chat_run_admission.py::test_repeated_complete_turns_share_the_workspace_agent_under_distinct_runs -x -q -s`.
It adds no repository test nodes and replaces no production authority.

```python
import asyncio
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    if item.name != "test_repeated_complete_turns_share_the_workspace_agent_under_distinct_runs":
        return
    container = item.funcargs["container"]
    records = list(container.capability_effects.invocation_store._items.values())
    assert len(records) == 2

    async def read():
        for row in records:
            run = await container.run_store.get_run(row.run_id)
            assert run is not None
            print("ACCEPTANCE_JOIN", run.workspace_id, row.workspace_id,
                  run.actor_principal_id, row.actor_id)
            assert row.workspace_id == run.workspace_id
            assert row.actor_id == run.actor_principal_id
    asyncio.run(read())
```

### Local history repair provenance

Nine message-only old -> new identities:

- 43731c7984d0 -> d17736a125e1
- 7c5c6c9a3c31 -> 4628d6ceae8c
- 6124afb907d6 -> 218906a02d72
- 0ab0bb698d63 -> a1e43039e0fa
- 58631e60a677 -> 6e5f4e0ddfb6
- c44240217fe1 -> e099bd69730a
- 4fd6dafb8a9a -> 1c99ad049dec
- e9aad735626d -> a37969b3a487
- 61f22af235f1 -> 7ee56860fc32

The develop-sync merge became `df4538183bf0`; all 115 rebuilt trees were byte-identical to their inputs. 83 signature headers were detached because they cannot authenticate changed parent/message bytes; original signed objects are preserved under both backup refs. Any future integration owner must account for this local history divergence (no push authorized or performed).

Progress summary: {checked: 1 issue, done: 3 bounded repairs (sync, inherited message text, false notes), skipped: 0 issues, errors: 1 acceptance join failure, next: configured-authority/actor/scope production repair and real-startup proof}. No test inventory delta in this round, no manual ledger/grant edit, no GitHub mutation.
