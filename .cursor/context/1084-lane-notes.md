---
lane: L1084
issue: "#1084 [M1-D2][#56] Converge shipped Hive chat and Agent model egress onto canonical Provider/Binding/Invocation"
round: "repair dea951bf, 2026-10-25 (supplied develop sync, CI replay, message-only history repair)"
head: 93ef338be (post-message-repair checkpoint; see 1084-repair-dea951bf.md for final evidence)
---

# 1084 lane notes (read before touching this branch)

## Current repair checkpoint (job dea951bf)

- The older sections below describe historical heads, not current verification.
- The supplied develop `2014ab888c0b` was merged without conflicts; it remains
  an ancestor after the bounded local history repair. No remote mutations.
- CI-exact Pyright is green (11 errors <= existing 21-error baseline), and
  exact-debt-ledger vulture is green (1297 findings == 1297 identities).
  Neither a speculative type fix nor a ledger amendment was warranted.
- The prior claim that no branch-only commit carried auto-close text was
  false. Nine reproduced messages were repaired locally, including commit
  bodies (quoting a keyword never protected it). Their trees, author/committer
  identities and timestamps are unchanged; descendant parent hashes changed.
  Original signed objects remain on local backup refs
  `auto-1084-before-message-repair-dea951bf` and
  `auto-1084-message-repair-input-dea951bf`. Rebuilt objects cannot preserve
  signatures over old content; no develop ancestor was rewritten.
- **Readiness remains NEEDS-REPAIR:** an additional read-only assertion over
  the real complete-route test fails: its Invocation records Workspace
  `default` and an empty actor, while the persisted Run records the selected
  Workspace and authenticated actor. Green suites did not assert this join.
  Full startup and production refusal-matrix proof remain unverified.
- Detailed scope, commands, residual acceptance gaps, and reproducible handoff:
  `.cursor/context/1084-repair-dea951bf.md`.

## 2026-10-25 CI-repair round (stub removal + Pyright root cause; this head)

- Named merge-queue failure `Quality / Pyright` root-caused: it fired at the
  OLD pre-reword tip `5769e4ac3` (not an ancestor of this branch) with
  "pyright regression: 22 errors exceeds baseline of 21" (job log 121005725910).
  The repair already in this branch's history is `849f134d5`. Proof at the
  current state: CI check-run `Quality / Pyright` = success at `7bc1e3c81`
  (run 40147725687, completed 2026-10-25T00:43:54Z) and local CI-exact replay
  (`uv sync --locked --all-extras`, `uv pip install -e packages/maistro-evolve`,
  `uv pip install pyright` -> 1.1.414, `pyright --outputjson
  packages/maistro-core/src` -> `check-pyright-report.py --baseline 21`)
  = 11 errors, gate exit 0.
- Develop sync is resolved and stays resolved: `origin/develop` = `9cc09cd57`
  = merge-base(HEAD, origin/develop), 0 behind, via true merge `67400d014`.
- Issue #1084 gap 2's letter is now closed: `build_llm_port` no longer selects
  the success-shaped `StubLLMPort` when LITELLM base/key are missing — it
  raises retryable 503 (Retry-After 5, same shape as admission's refusal),
  `execute_turn` closes the admitted Run FAILED, zero model effects.
  `stub_completion`/`StubLLMPort` are deleted from adapters/llm_http.py.
  NOTE: the earlier "unreachable post-admission (admission 503s first)"
  parenthetical was wrong — the bridge boots the Container with a placeholder
  URL and empty key (adapters/maistro_core.py), admission does not consult the
  gateway env, so the stub WAS reachable in an admitted turn.
- Regression pin: test_chat_run_admission.py::
  test_a_turn_past_admission_without_gateway_config_fails_closed — A/B proof:
  the identical test FAILS at `7bc1e3c81` (200 + stub content) and passes with
  the fix (503, Run FAILED). test_api.py's two former 200-stub smoke pins
  (`test_user_can_chat`, `test_chat_complete_stub`) were rewritten to the
  fail-closed contract count-neutrally (the latter renamed
  test_chat_complete_without_gateway_config_has_no_choices).
- Suite inventory: docs/testing/inventory-notes/1084-model-egress-
  convergence.md hive delta +3 -> +4 (one new node; renames count-neutral);
  all 21 suites match the ledger.
- Green at the repair tip: ruff check/format, hive backend suite 4022 passed
  /26 skipped, core egress/composition + server conductor + vision/voice/
  adapter focused suites 119 passed, vulture (CI args) 1297==1297, radon
  127==127, model-egress, design-model-egress, promotion-surface,
  direct-effects 51 dispositioned, reachability OK, ratchet-provenance 54
  consumers, suite-inventory 21 suites, pyright 11<=21 gate exit 0.
- HISTORICAL RESIDUAL (repaired locally in job dea951bf): closure keywords in
  commit bodies reachable from HEAD but absent from origin/develop —
  `e9aad7356` body line 34 "Closes #1127, #1098, #1056, #1109, #1143"
  (#1098/#1109/#1143 re-confirmed OPEN 2026-10-25; #1127/#1056 closed),
  `c44240217` body line 16 "fix #13" (#13 OPEN), `61f22af23` body line 8
  quoted 'resolve #1824' (#1824 OPEN; quotes do not stop GitHub's regex).
  Landing PR #2296 would auto-close those OPEN issues. Removal needs a
  `--rebase-merges` rebuild of ~20 commits incl. 6 merge commits — do not
  attempt ad hoc.

## State
- Branch = origin/develop (9cc09cd57, the current tip) + this issue's diff
  (55 files). Every develop sync so far was resolved as a true merge
  (eacde211a, then 90bd607be on 4de7e906d, d5117f56c on b1c89cdbc, and
  67400d014 on 9cc09cd57); merge-base HEAD origin/develop == the develop tip.
  Never re-resolve by hand-editing quality/*.json back toward old develop.
- Two repair commits follow: b728bca8a (census rekey after the radon refactor
  of execute_model_chat/_post_model_chat + bridge fakes), ee063fde9 (server
  chat door's conductor consumes persisted execution identities).
- The 2026-10-24 repair round resolves the NEEDS-DEEP-REVIEW streaming item:
  SPEC-285 (docs/specs/) specifies the narrow on_chunk observer seam, the
  gateway pumps chunks live, stream_chunks bridges them through a queue, and
  streamed calls now record usage from the terminal usage chunk.
- Reachability is GREEN (supersedes the earlier "stays red on
  admission_identity" note in this file): `check-reachability.py` exits 0 at
  this head (1462 modules, 149 unreachable, all ledgered), and the
  `Quality / Reachability` check-run is success on PR #2296.

## Ratchet traps hit this round (do not rediscover)
- radon: new/moved blocks must stay grade B; execute_model_chat and
  GovernedModelChatClient._call were C(14) before the split. Any edit that
  pushes a block to C fails check-radon-baseline with an unbaselined key.
- vulture: deleting get_default_quota_tracker (quota/default_tracker.py) would
  demand a vulture-baseline row prune (prohibited); it is used again by
  default_effect_context's ephemeral composition — keep that call.
- wiring-reads: Container.model_chat_client must keep a direct attribute read
  in production code (hive adapters/maistro_core.py); getattr hides it.
- direct-effects census (quality/direct-effect-call-sites.json +
  scripts/check_direct_effects.py _PATH_CALLS) is keyed by qualname — renaming
  llm_gateway functions means rekeying both, dispositions unchanged.
- suite inventory: note is docs/testing/inventory-notes/1084-model-egress-
  convergence.md (core +4, server +1, hive +2 vs develop).
- reachability was RED on older heads (maistro.runs.admission_identity, the
  inactive #1851 leaf) but is now ledgered — the gate exits 0 on this branch
  and on origin/develop; do not re-litigate it here.

## 2026-10-24 CI-repair round (head ab0abeba3 -> bc3841989)

- Resolved the develop sync conflict as a true merge (fb416cf38) on top of
  `4de7e906d`; no hand-edited quality/*.json rollback.
- The only local validation failure left at ab0abeba3 was the suite-inventory
  note: its `inventory-delta` named the root suite `tests`, which is not a
  recipe (`scripts/check-suite-inventory.py` RECIPES uses `tests/`). Renamed
  the key; the delta is 0 and all 21 suites now match the ledger.
- Re-verified the registry.yml `Validate ADR/spec front-matter` job end to end
  on this head: `maistro_registry.cli lint . --strict` 0 errors/0 warnings,
  `tools/lint_lifecycle.py`, `scripts/check-adr-index.py`,
  `scripts/check-adr-status-language.py`, the AC-Defined index (no diff),
  `scripts/check-citation-status-provenance.py` (0 exceptions), and the
  registry unit tests (194 passed).
- Also green on this head: ruff check/format, the core+server focused pytest
  (191 passed/2 skipped), the hive-conductor focused pytest (109 passed), the
  suite-inventory gates (21 suites), `check-vulture-baseline.py` (1302==1302),
  `check-promotion-surface.py`, `check-model-egress.py`,
  `check-design-model-egress.py`, `check_direct_effects.py`, radon (127==127),
  reachability, and `check-ratchet-provenance.py` (54 consumers classified).

## Open design item for the owner

- RESOLVED this round (SPEC-285, docs/specs/SPEC-285-model-egress-incremental-
  streaming.md): bounded work item 3's narrow callback/lifecycle design is
  specified, and the shipped path now honors it — _stream_body (llm_gateway.py)
  pumps normalized chunks to an on_chunk observer while the Invocation is
  RUNNING, stream_chunks bridges them live through a queue, and terminalization
  still happens only after full consumption (failure → FAILED/UNKNOWN,
  consumer abandonment → UNKNOWN cancel, dedup replay from the terminal
  record). Streamed calls now also record usage from the terminal usage chunk,
  which the buffered path lost entirely. Owner ratification of the streaming
  semantics is requested in the spec's ratification note; the admission owner
  decision (2026-09-23) is untouched.

## 2026-10-24 verify+repair round (head c26de4290)

- The develop-sync block is resolved and provable: `origin/develop` still is
  `4de7e906d`, `git merge-base HEAD origin/develop` equals it (0 commits
  behind), and the merge commit is `fb416cf38`; worktree clean.
- The named merge-queue gate failure (`integration-scope`) was the
  `durable-events` leg concluding failure at `b2447ac4` (UndefinedTableError
  on `capability_binding_revocations` at Container boot). The c26de4290 fix
  (PgBindingStore.ensure_schema in _select_effect_backend) was proven locally
  against postgres:17 with CI's exact job steps: events suite 490 passed,
  tests/migrations/test_event_schema_agreement.py 5 passed, both under
  MAISTRO_REQUIRE_PG_LEGS=1. Repro pair: booting a Container with the binding
  tables dropped succeeds with the fix and fails with the exact
  UndefinedTableError when ensure_schema is no-op'd.
- Added the missing regression test
  (tests/events/test_container_pg_durable_events.py::
  TestTheBindingStoreComesUpToo, +1 core test; note
  docs/testing/inventory-notes/1084-durable-events-binding-schema-boot.md).
  It fails against the regression when ensure_schema is bypassed and passes
  with the fix.
- Green on this head: ruff check/format, focused core+server pytest (191
  passed/2 skipped), hive-conductor focused pytest (109 passed), suite
  inventory (21 suites), check-vulture-baseline.py with CI args
  (1302==1302), check-model-egress.py (16 physical callers, no expansion),
  check-design-model-egress.py, check-promotion-surface.py,
  check_direct_effects.py (51 sites dispositioned).

## 2026-10-25 verify+repair round (reword 90bd607b, tip 849f134d)

- Named merge-queue failure `Quality / Pyright` was repaired at efed9c308
  (11 pyright errors vs baseline 21) and re-proven twice: locally with CI's
  exact env/command (`uv sync --locked --all-extras`, `uv pip install -e
  packages/maistro-evolve`, `uv pip install pyright` 1.1.414,
  `pyright --outputjson packages/maistro-core/src` ->
  `scripts/check-pyright-report.py pyright.json --baseline 21 --exit-code 1`
  = gate exit 0) and in the captured check-runs at efed9c308 (success).
- BLOCKING finding repaired: the lane-authored merge commit fb416cf38 said
  "resolve #1824" — a GitHub auto-close keyword targeting the OPEN sibling
  issue #1824; it would have closed #1824 when PR #2296 lands. Reworded to
  "conflict resolution for #1824 x #1084 adapter collision (no auto-close)".
- How the reword was done (do NOT redo with plain `git filter-branch --
  fb416cf38^..HEAD` — that range walks develop-side commits merged in AFTER
  fb416cf38^ and re-hashes them, duplicating develop history at merge time;
  merge-base fell to e20e9f52 in a first attempt). Instead the 16 commits on
  HEAD's first-parent chain from fb416cf38 to efed9c308 were rebuilt with
  `git commit-tree`, preserving trees/authors/committers/dates/messages byte
  for byte except the one subject line. New tip 849f134d: tree identical to
  efed9c308 (empty `git diff`), develop-side parents (4de7e906d, b1c89cdbc,
  ffc27cc43, db4d3eb09) untouched, `git merge-base HEAD origin/develop` =
  b1c89cdbc.
- RESOLVED: the reword divergence was force-pushed; PR #2296 head is now
  67400d014, identical to this branch tip.
- All gates re-run green at the reworded head (same tree as efed9c308):
  ruff check + format, pyright ratchet (11<=21), vulture CI args
  (1297==1297), radon (127==127), reachability exit 0, wiring-reads,
  check-model-egress, check-design-model-egress, check_direct_effects
  (51 dispositioned); pytest: hive backend 4007 passed/26 skipped, server
  647 passed/10 skipped, focused core egress/conductor/wiring/quota/warden
  224 passed, root model-egress+bench 64 passed.

## 2026-10-25 independent-verification round (head 67400d014)

- develop sync is current: `git merge-base HEAD origin/develop` = 9cc09cd57 =
  origin/develop tip; worktree clean; PR #2296 head == branch tip; the
  pre-round "develop sync conflict preserved" block is resolved.
- CORRECTION (job dea951bf): the original blanket no-keywords claim at this
  historical head was false. Nine branch-only commit messages still contained
  closing text, including quoted text in commit bodies. The current repair
  rewords all nine locally and scans the full supplied-develop..HEAD range;
  PR/GitHub state was not mutated or re-enumerated.
- The previously failing `Quality / Pyright` gate re-proven CI-exact at this
  head: `uv sync --locked --all-extras`, `uv pip install -e
  packages/maistro-evolve`, `uv pip install pyright` (1.1.414),
  `pyright --outputjson packages/maistro-core/src` -> 11 errors / 54 warnings,
  `scripts/check-pyright-report.py --baseline 21 --exit-code 1` exits 0.
  (CI failed this gate at 5769e4ac3; success run at efed9c308; the 67400d014
  run was still QUEUED at verification time — pending CI stays UNVERIFIED.)
- Re-executed green at 67400d014: ruff check + format (3498 files), mypy
  --strict maistro-core (827 files, 0 issues), reachability exit 0 (1462
  modules, 149 unreachable, ledgered), vulture CI args 1297==1297 (base
  9cc09cd57), radon 127==127, check-model-egress (16 physical callers, no
  expansion), check-design-model-egress, check_direct_effects (51
  dispositioned), wiring-reads, check-ac-state --run-tests --ratchet,
  suite inventories (hive 4047, core 17931, server 657 — all match).
- Focused suites re-executed: core egress/conductor/wiring/quota/warden/
  composition + server conductor_agent 290 passed/11 skipped; hive
  admission/dag/gateway/adapters/vision 117 passed. Admission tests run a
  real embedded Container with only the httpx transport mocked.
- No inventory-note change needed: docs/testing/inventory-notes/
  1084-model-egress-convergence.md deltas still match (all suite gates pass).
