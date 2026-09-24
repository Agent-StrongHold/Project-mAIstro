# repair-1171 — canonical Warden composition on Conductor + event re-entry

## Second validation round (job 0387d5b6, head d461035)

`check-4.log` failed on exactly one stale test fake:
`test_maistro_core_adapter.py::test_start_carries_the_model_bindings_onto_the_container_config`
still declared `fake_create_container(config)` without `**kwargs`, so the
bridge's intentional `warden_llm=` kwarg raised `TypeError`. The other five
fakes in the file had already been widened; this one was missed. Fix: accept
`**kwargs` like its siblings (test-only, one line). Re-run: 80 passed for the
conductor suite, 133 passed for the core issue suites, ruff/mypy/gates clean.

## What the prior validation actually failed on

`check-1.log` (job c669514f) recorded 47 ruff `invalid-syntax` errors — all a
cascade from one unresolved conflict-marker block in
`packages/maistro-core/src/maistro/container.py` (lines 492–497), committed
as-is by merge `bf5f6ed47`. Nothing about the Warden composition itself was
flagged; the tree did not parse, so no check could run.

## Repair

- Commit `efe9ab2a6`: resolved the leftover `<<<<<<< HEAD` block in
  `Container.chat`, keeping the HEAD-side comment (identity resolution at the
  canonical chat boundary) and dropping the markers. Byte-minimal: −3 lines.

## Acceptance verification (production code reachable at `efe9ab2a6`)

The substance of #1171 was already implemented on this branch by
`7a32346cf` (compose conductor Warden across re-entry paths), `1d064334a`
(refresh harness Warden composition), and `f137c9af8` (scan harness startup
context). Verified against current code, not claims:

1. **Canonical composition, no route-local instances** — `EngineService.warden`
   returns `container.warden` and raises `WardenCompositionUnavailable`
   otherwise (`services/engine.py`); `routes/harness.py` and
   `services/agent_materialization._warden()` both consume it; grep proves no
   `Warden()` construction under `packages/hive-conductor/backend` outside
   tests; the Container binds its own Warden into the EventBus
   (`_wire_event_handlers`, `container.py`).
2. **Same layers/policy incl. LLM judge** — one `Warden` instance built as
   `Warden(llm=warden_llm)` in `create_container` backs chat's Gate, agent
   scan, harness manager, and event handlers; the Conductor bridge passes the
   configured client (`warden_llm=llm_client if llm_key else None`).
3. **Fail closed** — harness 503 on `WardenCompositionUnavailable` /
   `HarnessSecurityUnavailable` (incl. broken-Warden test); agent scan 503 via
   `AgentScannerUnavailable`, nothing stored; event re-entry raises
   `EventSecurityUnavailable` before any HTTP; `conductor_chat` is absent from
   `BUILTIN_HANDLERS` and registerable only via `handlers_for_warden`.
4. **Exact-representation scan at re-entry** — `conductor_chat_action` scans
   the labelled message string asserted equal to the HTTP payload content,
   boundary `tool_result`.
5. **Blocked preview is not an instruction channel** — a blocked
   `security_event_escalation` preview fails the whole action with
   `EventPayloadBlocked` before any POST; integration test asserts zero HTTP
   calls.
6. **Provenance labels** — `[maistro event re-entry; provenance=handler_metadata]`
   vs `[untrusted event payload; boundary=tool_result] … [/untrusted event payload]`.
7. **#1158 inherited** — `normalize_for_detection` runs inside `Warden.scan`;
   no route/event-specific normalizer exists (grep).
8. **Cross-path equivalence proof** —
   `test_identical_malicious_content_uses_one_canonical_warden`
   (`test_harness_routes.py`): identical malicious string through chat (blocked
   at gate, model asserted unreachable), agent scan (flagged), harness send
   (400), and Container-style bound EventBus re-entry (refused pre-HTTP) —
   exactly 4 scans, boundaries `user_input×3 + tool_result`, one Warden.

## Validation evidence

- `uv run pytest` issue-scoped suites (core events, harness_runner, container
  security wiring, conductor harness/agents/chat-created-agents):
  **463 passed, 51 skipped**.
- `uv run ruff check .` — clean. `uv run ruff format --check .` — 2510 files formatted.
- `uv run mypy` (6 packages) — success, 711 files.
- Gates: `check-wiring-reads`, `check-cross-package-imports`,
  `check-contract-markers` — all OK.

## Residual, out of scope (pre-existing at pre-merge head `599fb7917`, verified)

- 23 scheduler + 18 HITL fixture failures in the full conductor suite: the
  session-scoped conftest fake container (`SimpleNamespace`) predates
  `graph_run_store` / `capability_effects` reads merged from develop; identical
  failures at the pre-merge head. Scheduler went 27→23 failed after this
  repair (tree parses again). Belongs to the scheduler/HITL lanes.
- `test_log_redaction.py::test_install_is_idempotent` fails standalone at the
  pre-merge head too; log-redaction concern, not #1171.

## Repair round 2 (job ada94cfec, head d2ed9974) — residual re-attributed and FIXED

The "residual, out of scope" claim above was wrong: at develop base `8bb344e3`
the full backend suite passes completely (2653 passed / 1 skipped, verified in
an isolated worktree). The 43F + 20E at the branch head were introduced by this
branch's conftest swap (`StubAgentPort()` → bare `SimpleNamespace` container):
store/scheduler services read the full Container surface and treat "container
present" as "canonical spine present", so a partial fake broke ~60 tests
(AttributeError on `graph_run_store`/`capability_effects`,
`ScheduleAdmissionUnavailable`), while a container-less session engine
(correctly) fail-closed the chat/voice/HITL gate stack, breaking ~20 tests
written against the removed process-global Warden.

Fix:
- `services/engine.py`: explicit `set_warden_composition()` slot — the
  composition-root seam for hosts without a Container. `warden` reads the
  Container first, then the slot, else raises `WardenCompositionUnavailable`
  (fail-closed preserved; routes still construct nothing).
- `conftest.py`: `StubAgentPort()` restored + one canonical `Warden()`
  installed via the slot; every scanning route shares it.
- The three fail-closed tests that patch `container=None` now also clear the
  slot (monkeypatch) — the exact condition they test.

Evidence at repaired head: full backend suite **2663 passed / 1 skipped / 0
failed**, no hang; core issue suites 393 passed / 51 skipped; conductor issue
suites + hitl door 100 passed; ruff clean; `check-suite-inventory` (both),
`check-wiring-reads`, `check-reachability` exit 0. Named acceptance tests
(equivalence across chat/scan/harness/event re-entry, L3 wiring, labelled
re-entry scan, blocked-preview refusal, missing-warden refusal) all pass.
Details: docs/testing/inventory-notes/auto-1171-warden-composition.md.

## Round 3 (job 1fa1f2d0, head 5efd26eee) — independent re-proof, no code change

Verify job cafb5487 at this head had **all seven checks returncode 0** but the
verifier agent crashed (`worker_error`), producing no findings. This round
re-ran the full battery from scratch and re-proved every acceptance criterion
on current code: ruff clean; core issue suites 393P/51S; conductor issue
suites 80P (incl. the previously failing adapter test — fixed by fe7ba28c5);
full backend 2663P/1S/0F; mypy 712 files clean; five CI gates exit 0.
Equivalence test re-read: same Warden object across chat/scan/harness/event
re-entry, exactly 4 scans (user_input×3 + tool_result), zero HTTP after a
blocked preview. Inventory note round 3 section records the details.

## Round 7 (job cdbffdb59, head d08c4f7f2) — repair-lane validation, no code change

Round 6 was rejected purely for process (verify-phase agent mutated the
worktree by committing evidence; result.json: `worktree_changed`). This round
re-ran the whole battery first-hand at that head BEFORE touching the tree:
ruff clean/format clean; core issue suites 133P; conductor issue suites 80P;
harness routes 13P incl. the 4-path equivalence test by name; handler +
container L3 named proofs 8P; full backend suite 2670P/1S/0F (82 s); mypy
713 files success; five CI gates exit 0 (suite-inventory ×2, reachability,
wiring-reads, cross-package-imports, contract-markers). All eight acceptance
criteria hold with first-hand evidence; no production/test repair warranted.
Details: docs/testing/inventory-notes/auto-1171-warden-composition.md (round 7).
