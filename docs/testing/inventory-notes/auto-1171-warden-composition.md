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

No closure keywords (`fixes/closes/resolves #…`) in branch commit messages;
PR #1447 body says "Refs #1171" only and remains draft.
