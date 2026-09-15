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
