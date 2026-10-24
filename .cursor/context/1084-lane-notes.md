---
lane: L1084
issue: "#1084 [M1-D2][#56] Converge shipped Hive chat and Agent model egress onto canonical Provider/Binding/Invocation"
round: "verify+repair, 2026-10-25 (pyright ratchet + fb416cf38 auto-close reword)"
head: 849f134d (tip of auto-1084; tree-identical to pre-reword efed9c308)
---

# 1084 lane notes (read before touching this branch)

## State
- Branch = origin/develop + this issue's diff (23 files). The blocked develop
  sync was resolved as a true merge commit (eacde211a); never re-resolve it by
  hand-editing quality/*.json back toward old develop.
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
- RESIDUAL: the reword rewrote commit hashes, so local auto-1084 (849f134d)
  and the remote PR #2296 head (still efed9c308) have diverged. The driver
  must force-push this branch before merge; the PR diff/tree is unchanged.
- All gates re-run green at the reworded head (same tree as efed9c308):
  ruff check + format, pyright ratchet (11<=21), vulture CI args
  (1297==1297), radon (127==127), reachability exit 0, wiring-reads,
  check-model-egress, check-design-model-egress, check_direct_effects
  (51 dispositioned); pytest: hive backend 4007 passed/26 skipped, server
  647 passed/10 skipped, focused core egress/conductor/wiring/quota/warden
  224 passed, root model-egress+bench 64 passed.
