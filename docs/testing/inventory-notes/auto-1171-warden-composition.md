---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/hive-conductor/backend/tests: +10
---
# auto-1171 — canonical Warden composition at Conductor and event re-entry boundaries

Added regression coverage for the issue's security boundaries:

- core event and harness tests add five nodes: event conductor actions scan the
  exact labelled model message with the `tool_result` boundary, refuse blocked
  previews before HTTP, refuse when the canonical Warden is unavailable, and
  scan the untrusted startup AgentSpec before harness creation;
- the Conductor agent scan reads the application Container Warden and returns a
  503 when that composition is absent;
- the harness manager reads the application Container Warden, scans startup
  AgentSpec content before provider creation, and its route returns a 503 when
  the composition is absent (or 400 when startup content is blocked);
- a cached manager is rejected after Container teardown, and one integration
  test sends identical malicious content through chat, agent-scan, harness,
  and a Container-style bound EventBus event re-entry using the same Warden
  instance;
- direct event re-entry no longer has a process-global Warden fallback:
  `conductor_chat` is registered only by `handlers_for_warden`, and tests prove
  the unbound built-in map cannot invoke it;
- Container wiring proves an injected LLM judge reaches layer 3 through the
  per-Container event bus, and the Conductor bridge passes its configured
  client into that composition.

## Independent verification round (job 8fb6064f, head fe7ba28c)

Re-derived all eight acceptance criteria at the exact head and re-executed:

- `uv run pytest` core issue suites (container security wiring, events handlers,
  events, harness_runner): **133 passed**; conductor issue suites (conftest,
  agents routes, chat-created agents, harness routes, maistro-core adapter):
  **80 passed**. Named acceptance tests pass individually:
  `test_identical_malicious_content_uses_one_canonical_warden`,
  `test_container_warden_composition_reaches_l3_and_event_reentry`.
- `uv run ruff check .` clean; `scripts/check-reachability.py` exit 0 (the
  removed `maistro.events.handlers` baseline entry is a legitimate cutover:
  the module is now reachable via the Container's `_wire_event_handlers`);
  both `check-suite-inventory.py` gates OK.
- Production grep: zero `Warden(` construction under
  `packages/hive-conductor/backend` outside tests; remaining core/RSI
  `Warden()` fallbacks (output_security.py:85, agent_synth_dag.py:307,
  maistro_rsi) are pre-existing at base 8bb344e and outside this issue's
  named Conductor-route/event scope.
- Residual confirmed, unchanged from the repair note: `test_scheduler.py`
  fails 23/65 with `AttributeError: ... attribute 'run_store'` — the
  session-scoped conftest fake container predates develop's Run-store reads;
  unrelated to Warden (scheduler/HITL lanes).

## Repair round 2 (job ada94cfec, head d2ed9974): regression in the session
conftest, now fixed

The prior round's residual attribution was **wrong**. Re-running the full
`packages/hive-conductor/backend/tests` suite at the develop base `8bb344e3`
in an isolated worktree passed completely (2653 passed, 1 skipped), so the
43 failures + 20 errors observed at the branch head were a regression
introduced by this branch's `conftest.py` edit, not pre-existing scheduler
debris.

Mechanics: the branch's session fixture replaced `StubAgentPort()` with
`SimpleNamespace(container=SimpleNamespace(warden=Warden()))`. Store/scheduler
services read the full Container surface off `_agent_port.container` and treat
"container present" as "canonical spine present" — a partial fake turned those
reads into `AttributeError` (`graph_run_store`, `capability_effects`) and
fail-closed `ScheduleAdmissionUnavailable`, while the same truthy-but-bare
fake also broke the fail-closed semantics those services define for
"container absent". Conversely, reverting to a container-less session engine
fail-closed the chat/voice/HITL gate stack (`scan_config` → `engine.warden`),
which is correct production behavior under #66 but broke ~20 tests written
when the scanner was the removed process-global bare Warden.

Repair (no production semantics weakened):

- `services/engine.py` gains an explicit `set_warden_composition()` slot:
  the composition-root seam for a host with no Container. `warden` reads the
  Container first, then the installed composition, and raises
  `WardenCompositionUnavailable` when neither exists — fail-closed preserved;
  routes still construct nothing.
- `conftest.py` restores `StubAgentPort()` (standalone semantics for every
  store service) and installs one canonical `Warden()` via the new slot, so
  chat/voice/HITL/harness/agent-scan routes all share a single detector —
  still one composition, not a route-local instance.
- The three tests that express "no composition" via `container=None`
  (`test_agent_scan_fails_closed_without_container_security_composition`,
  `test_start_fails_closed_without_container_security_composition`, and the
  manager-rebuild test) now also clear the slot with monkeypatch, which is
  the exact condition they mean to exercise.

Evidence at the repaired head: full backend suite **2663 passed, 1 skipped**
(10 more than base — the new security tests), no hang (the prior stall was
the scanner-error path inside a stream-cancellation test, unreachable once
scanning works); core issue suites 393 passed / 51 skipped; conductor issue
suites + hitl door 100 passed; `ruff check`/`format` clean;
`check-suite-inventory.py` (both suites), `check-wiring-reads.py`, and
`check-reachability.py` all exit 0; no test-count delta (inventory unchanged:
2664 / 10744 collected).

No closure keywords (`fixes/closes/resolves #…`) in branch commit messages;
PR #1447 body says "Refs #1171" only and remains draft.

## Validation round 3 (job 1fa1f2d0, head 5efd26eee) — independent re-proof

The verify job at this head (cafb5487) recorded **returncode 0 on all seven
checks** but crashed afterwards (`worker_error`, agent_exit 1), leaving no
findings. This round re-ran the battery from scratch at the same head; every
number below was measured fresh, not carried forward:

- `ruff check .` / `ruff format --check .`: clean (2527 files formatted).
- Core issue suites (events, harness_runner, container security wiring):
  **393 passed / 51 skipped**.
- Conductor issue suites (agents, harness, adapter, chat-created):
  **80 passed**, including `test_start_carries_the_model_bindings_onto_the
  _container_config` — the one test check-4.log (job 0387d5b6, head d461035)
  actually failed on; the `**kwargs` fake widening in fe7ba28c5 fixed it.
- Full backend suite: **2663 passed / 1 skipped / 0 failed** (~2 min).
- `mypy` (6 packages): success, 712 files.
- Gates: `check-suite-inventory` (conductor 2664 / core 10744, no delta),
  `check-wiring-reads`, `check-cross-package-imports`,
  `check-contract-markers`, `check-reachability` — all exit 0.
- `test_identical_malicious_content_uses_one_canonical_warden` re-read line by
  line: asserts the *same* Warden object serves chat (blocked at gate, model
  asserted unreachable), agent scan (flagged), harness send (400), and
  Container-style bound EventBus re-entry (`EventPayloadBlocked` cause,
  `event_client.calls == []`); exactly 4 malicious scans with boundaries
  `user_input×3 + tool_result`.
- #1158 inheritance re-proven structurally: `normalize_for_detection` is
  invoked inside `Warden.scan` (`security/warden/detector.py:146`); grep
  finds no route/event-local normalizer.

No code change was warranted this round: the only prior real failure is
demonstrably fixed at this head, and no acceptance criterion lacks evidence.

## Verification round 4 (head 8151b3e2b, post-develop merge) — independent re-proof

Round-4 lane job a9ba2786 (this head) ran all seven driver checks green; the
"prior validation failed" pointer resolves to job 8915763e, whose result.json
shows **returncode 0 on all seven checks** followed by a provider
context-size crash (`exceeds 16384 tokens`) — infra, not a code failure. Every
number below was re-measured fresh at the exact head, not carried forward:

- `ruff check .` clean; `ruff format --check .`: 2528 files already formatted.
- Core issue suites (harness_runner, events, handlers, container security
  wiring): **133 passed**. Conductor issue suites (agents, chat-created,
  harness, adapter): **80 passed**, including
  `test_start_carries_the_model_bindings_onto_the_container_config` — the test
  job 0387d5b6's check-4 had failed before fe7ba28c5.
- Full backend suite re-run: **2663 passed / 1 skipped** (~79 s) — matches the
  recorded inventory (2664 collected) with no collateral regression from the
  engine/conftest composition seam.
- `mypy` (documented six-package command): Success, 712 files. (Running
  `mypy packages/maistro-core/src` alone shows 5 pre-existing
  `maistro_bootstrap.*` import-not-found errors in untouched `cli/` files —
  resolved by the documented command that includes `maistro-bootstrap/src`.)
- Gates: `check-suite-inventory.py` both suites ok; `check-reachability.py`
  exit 0 (188 unreachable; the pruned `maistro.events.handlers` entry is the
  ratchet's required action after container.py's `_wire_event_handlers`
  import made the module reachable).
- Acceptance re-derived: all eight criteria hold at this head. Chat and
  agent-scan converge on `scan_config` → `engine.warden`; harness routes and
  `HarnessSessionManager` read the same `engine.warden`; event re-entry is
  bound per-Container via `handlers_for_warden` (`conductor_chat` absent from
  `BUILTIN_HANDLERS`), scans the exact labelled POSTed string at the
  `tool_result` boundary, and fails closed (`EventSecurityUnavailable` /
  `EventPayloadBlocked`) before HTTP. #1158 hardening is structural:
  `normalize_for_detection` runs inside `Warden.scan` (detector.py:146) and no
  route/event-local normalizer exists.
- Closure-keyword review: PR #1447 body is "Draft auto-opened … Refs #1171"
  (no closure keyword); branch commit messages contain no
  fixes/closes/resolves-#N (sole regex hit is the prose word "fail-closes").
- Non-blocking observations: `warden_llm` is gated on a configured LLM key in
  the bridge (`llm_client if llm_key else None`), so a keyless-LLM deployment
  runs layers 1–2.5 only — path parity (the acceptance requirement) still
  holds because every consumer shares that one instance, and the code comment
  documents the intent; `SafeHarnessRunner.start_session` uses a
  function-local `import json` (style nit, ruff-clean).

## Independent verification round 5 (job 21c90ffd, head 18e5ba9f) — no code change

Re-ran the full battery from scratch on the exact merge head; no check-*.log
was supplied with this job, so all evidence below is first-hand:

- `ruff check .` clean; `ruff format --check .` 2528 files formatted.
- Core issue suites (events, container security wiring, harness_runner):
  **393 passed / 51 skipped**.
- Conductor issue suites (harness routes, agents routes, chat-created agents,
  maistro-core adapter, agent materialization): **105 passed**.
- Full conductor backend suite: **2663 passed / 1 skipped / 0 failed** (89.8 s).
- `mypy` (documented six-package command): Success, 712 source files.
- Gates exit 0: check-wiring-reads, check-cross-package-imports,
  check-contract-markers, check-suite-inventory, check-reachability.
- Acceptance re-derived on production code at this head: engine.warden
  (services/engine.py:84) is the only composition source and raises
  WardenCompositionUnavailable; zero `Warden(` constructions in conductor
  production code; adapter passes `warden_llm` into `create_container`
  (maistro_core.py:195) whose single `Warden(llm=…)` (container.py:1540) backs
  chat gate → scan_config, agent scan, harness manager, and the per-Container
  EventBus binding (handlers_for_warden; conductor_chat absent from
  BUILTIN_HANDLERS). conductor_chat_action (events/handlers.py:121) scans the
  exact labelled POSTed message at the tool_result boundary before any HTTP,
  so a blocked security_event_escalation preview cannot re-enter as an
  instruction channel; provenance/boundary labels separate handler metadata
  from payload; normalize_for_detection runs only inside Warden.scan
  (detector.py:146). The four-path equivalence test
  (test_identical_malicious_content_uses_one_canonical_warden) executed green
  in this round: 4 scans, user_input×3 + tool_result, one Warden, zero HTTP
  after the blocked preview.

## Repair-lane validation round 7 (job cdbffdb59, head d08c4f7f2) — no code change

Round 6's evidence was rejected by its driver solely for process: the verify-phase
agent committed evidence docs, mutating the worktree under test (result.json:
`failure_kind: worktree_changed`). The code itself was never implicated. This
writer-lane round re-proves every acceptance criterion first-hand at that exact
head, before any tree mutation, so the numbers below describe the code as
validated:

- `ruff check .` clean; `ruff format --check .`: 2533 files already formatted.
- Core issue suites (harness_runner, events, handlers, container security
  wiring): **133 passed**. Conductor issue suites (conftest, agents routes,
  chat-created agents, harness routes, maistro-core adapter): **80 passed**.
- `packages/hive-conductor/backend/tests/test_harness_routes.py` full file
  verbose: **13 passed**, including by name
  `test_identical_malicious_content_uses_one_canonical_warden` (one Warden
  instance, 4 scans: `user_input`×3 via chat content_filter / agent-scan
  flagged / harness 400, plus `tool_result` via the Container-style bound
  EventBus, `TriggerActionFailure` with `EventPayloadBlocked` cause,
  `event_client.calls == []`) and
  `test_cached_manager_does_not_survive_container_security_teardown`.
- Named re-entry proofs: `TestConductorChatAction` (8 tests incl.
  `test_scans_exact_labelled_reentry_with_tool_result_boundary`,
  `test_blocked_preview_never_reaches_conductor`,
  `test_missing_warden_fails_closed_before_http`) plus
  `test_container_warden_composition_reaches_l3_and_event_reentry` (the
  configured layer-3 judge is consulted on the event path): **8 passed**.
- Full conductor backend suite: **2670 passed / 1 skipped / 0 failed** (82 s).
- `mypy` (documented six-package command): Success, 713 source files.
- Gates exit 0: check-suite-inventory (conductor 2671 / core 10783),
  check-reachability, check-wiring-reads, check-cross-package-imports,
  check-contract-markers.
- Structural re-checks at this head: zero `Warden(` construction under
  `packages/hive-conductor/backend` production code; `engine.warden`
  (services/engine.py:84) is Container-first and raises
  `WardenCompositionUnavailable` with neither source; `conductor_chat` remains
  absent from `BUILTIN_HANDLERS` and is registered only via
  `handlers_for_warden` from `container._wire_event_handlers`; the production
  `get_event_bus()` singleton has no production callers;
  `normalize_for_detection` runs only inside `Warden.scan`
  (detector.py:155) with no route/event-local normalizer; conductor_chat_action
  (events/handlers.py:117) scans the exact labelled string it later POSTs,
  with `provenance=handler_metadata` / `boundary=tool_result` labels keeping
  handler metadata distinct from payload text.

All eight acceptance criteria hold at this head with first-hand evidence; no
repair to production code or tests was warranted this round.

## Independent verification round 6 (job 50922cfc, head 1c11d63de) — no code change

Supplied check-*.log files all returncode 0 (uv sync, ruff check, ruff format,
core issue suites 133 passed, conductor issue suites 80 passed, both
check-suite-inventory runs). First-hand re-execution on this exact head:

- Core issue suites: **133 passed**; conductor issue suites: **80 passed**;
  `test_identical_malicious_content_uses_one_canonical_warden` seen passing by
  name (4 scans of one Warden: user_input×3 + tool_result, zero HTTP).
- Full conductor backend suite: **2670 passed / 1 skipped / 0 failed** (92 s).
- `ruff check .` clean; `mypy` six-package command: success, 713 source files.
- Gates exit 0: check-reachability (baseline legitimately drops
  maistro.events.handlers — now imported by container._wire_event_handlers),
  check-suite-inventory (both suites), check-wiring-reads,
  check-cross-package-imports, check-contract-markers.
- Structural re-checks: no production `EventBus(` outside the Container
  (`get_event_bus` singleton has no production callers); `conductor_chat`
  absent from `BUILTIN_HANDLERS` and registered only via
  `handlers_for_warden` at Container wiring; commit messages and PR #1447
  body contain no closure keywords.

## Independent verification round 8 (job f31ec541, head a2fb1a23b) — no code change

Verify lane at the post-merge head (`60862b6c5` develop merged into auto-1171).
Supplied check-*.log files all returncode 0. First-hand re-execution on this
exact head:

- Core issue suites (harness_runner, events, container security wiring):
  **133 passed**; conductor issue suites (agents/harness/chat-created/
  adapter routes): **80 passed**.
- Full conductor backend suite: **2677 passed / 1 skipped / 0 failed** (65 s),
  matching the recorded inventory count 2678.
- `ruff check .` clean; `mypy` six-package command: success, 713 source files.
- Gates exit 0: check-suite-inventory (conductor 2678 / core 10825),
  check-reachability (1117 production modules), check-wiring-reads,
  check-cross-package-imports, check-contract-markers.
- Acceptance re-derived from the issue, not from summaries: engine.warden is
  Container-first with `WardenCompositionUnavailable` fail-closed (engine.py);
  harness `_get_manager` discards managers from replaced compositions and
  routes map unavailability to 503; agent scan surfaces
  `AgentScannerUnavailable` → 503 with nothing stored; `conductor_chat` is
  registered only via `handlers_for_warden` from `_wire_event_handlers`, scans
  the exact labelled string it POSTs at boundary `tool_result`, and a blocked
  `security_event_escalation` preview raises `EventPayloadBlocked` before any
  HTTP; `Warden(llm=warden_llm)` in `create_container` gives chat, agent scan,
  harness, and event re-entry one composition including the layer-3 judge
  (`test_container_warden_composition_reaches_l3_and_event_reentry` proves the
  configured judge is consulted and a replacement Container's judge is not).
  `test_identical_malicious_content_uses_one_canonical_warden` seen passing:
  4 scans of one Warden instance, boundaries user_input×3 + tool_result.
- No closure keywords in PR #1447 body ("Refs" only) or branch commit messages.
- Environment-only, pre-existing, out of scope: re-produced
  `test_log_redaction.py::test_install_is_idempotent` failing under pytest's
  logging plugin (two plugin LogCaptureHandlers attach to the logger during
  the call phase and get wrapped, so the strict `== 0` assertion sees 2);
  passes with `-p no:logging` and in a bare-python probe; file untouched by
  this branch (initial-release provenance). Full backend suite at this head
  is 0 failed, so no lane impact.

## Repair-lane validation round 9 (job 5d987053, head 44105bc7) — no code change

Round 8's evidence was process-rejected (`worktree_changed`: the verify agent's
own evidence commit moved head a2fb1a23b → 44105bc7), so this round re-derived
every acceptance criterion first-hand at 44105bc7 — whose diff vs a2fb1a23b is
the round-8 docs commit only. Commands and outcomes, all run in this worktree:

- `uv run ruff check .` — all checks passed; `uv run ruff format --check .` —
  2533 files already formatted.
- Core issue suites (harness_runner, test_events, test_handlers,
  test_container_security_wiring): **133 passed** (2.8 s).
- Conductor issue suites (conftest, agents, chat-created-agents, harness,
  maistro-core adapter): **80 passed** (3.0 s) — includes the adapter test that
  job 0387d failed on (`fake_create_container` now accepts `warden_llm`).
- Full conductor backend suite: **2677 passed / 1 skipped / 0 failed** (86.6 s)
  = recorded inventory 2678. `check-suite-inventory` both suites: ok
  (conductor 2678, core 10825).
- `uv run mypy` (six-package command): success, no issues in 713 source files.
- Named acceptance nodes re-run by name: equivalence test + event handler
  suite 38 passed; harness/agents `-k "warden or scan or fail"` 29 passed.

Criteria re-derived from source at this head, not from summaries:

1. Canonical composition: `EngineService.warden` reads the Container first,
   then the explicit composition slot, else raises
   `WardenCompositionUnavailable` (engine.py:84-101); zero `Warden()`
   constructions under `packages/hive-conductor/backend` outside tests (grep).
2. Same layers incl. L3 judge: one `Warden(llm=warden_llm)` in
   `create_container` (container.py:1540) backs Gate, harness, agent scan, and
   the bound EventBus (`_wire_event_handlers`, container.py:1445-1449, 1769);
   `policy_version = WARDEN_POLICY_VERSION` on that one instance
   (detector.py:129); tool_result L3 classification on the same object
   (detector.py:190-193); L3 reachability proven by
   `test_container_warden_composition_reaches_l3_and_event_reentry`.
3. Fail closed: harness 503 (`test_start_fails_closed_without_container_
   security_composition`, `..._when_container_warden_cannot_scan`), agent scan
   503 with nothing stored (`AgentScannerUnavailable`,
   agent_materialization.py:114-128; named agent-route tests), event re-entry
   `EventSecurityUnavailable` before any HTTP
   (`test_missing_warden_fails_closed_before_http`).
4. Exact-representation re-entry scan: `conductor_chat_action` scans the very
   labelled string it later POSTs (handlers.py:121-143, boundary
   `tool_result`).
5. Escalation preview is not an instruction channel: scan precedes any HTTP
   and a blocked preview raises `EventPayloadBlocked`; equivalence test
   asserts `event_client.calls == []`.
6. Provenance labels: `[maistro event re-entry; provenance=handler_metadata]`
   vs `[untrusted event payload; boundary=tool_result] … [/untrusted event
   payload]`.
7. #1158 inherited: `normalize_for_detection` runs inside `Warden.scan`
   (detector.py:155); no security normalizer exists in Conductor production
   code (grep hits are LLM payload-shape adapters only).
8. Cross-path equivalence: `test_identical_malicious_content_uses_one_
   canonical_warden` — one Warden object, exactly 4 scans (user_input ×3 +
   tool_result), blocked chat never reaches the model, harness 400, flagged
   agent scan, zero HTTP after a blocked escalation preview.
