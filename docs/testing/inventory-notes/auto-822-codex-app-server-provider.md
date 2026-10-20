---
inventory-delta:
  packages/maistro-core/tests: +27
---

# Codex App Server as a governed HarnessRunner provider (issue #822 / auto-822)

Twenty-seven node IDs in `test_codex_app_server_harness.py` (new) cover the
`codex_app_server` provider end to end — the provider seam itself, the governed
`HarnessSessionManager` effect path, and the canonical graph-node executor —
against the issue's acceptance list (successful turn, streaming, tool request,
denied effect, provider crash, cancellation, session cleanup).

**+6** `TestProviderSurface`: identity/preference (`PREFERRED_CODEX_PROVIDER`),
healthcheck, foreign-thread correlation, envelope + `provider_metadata`
(maistro session id authoritative, codex thread id as metadata), model flag +
system-message exclusion, unknown-session `KeyError`.

**+6** `TestTruthfulProjection`: failed session create fails closed with no
half-registered session (sandbox released); failed turn and unparseable /
non-object results raise `CodexTurnError` instead of fabricating success;
stop releases thread mapping + sandbox; stop is idempotent and survives a
failing foreign stop command; post-stop turns raise `KeyError` (typed
cancellation projection).

**+3** `TestStreamProjection`: NDJSON App Server events project to canonical
observation (`codex.<kind>`, effect requests as gateable `tool_call`), field
correlation on every event; unparseable lines surface as `error` events with a
`failed` terminal status; non-zero stream exit projects `failed` — never a
silent success.

**+2** `TestMicroVMWiring`: factory boots the microVM at the pointed-at
workspace with exactly the scoped credential env (no broad service tokens
cross the VM boundary); runner end-to-end turn inside the VM.

**+8** `TestGovernedIntegration`: full lifecycle through governed Invocation;
denied effect dropped by the ActionGate before surfacing; Warden blocks
inbound before Codex sees it; provider crash raises through Invocation (failed
attempt, no fabricated envelope); unhealthy provider degrades to typed
`Unavailable` (SAFE_NOOP); cancellation projects as unknown-session
`Unavailable`; recorded Invocations carry maistro's canonical
run/NodeRun/Attempt identity (foreign thread id stays metadata); harness
output cannot mint new sessions/runs (Codex is not a peer scheduler).

**+2** `TestGraphNodeIntegration`: a canonical graph node runs a codex turn via
`HarnessNodeExecutor` → `HarnessOutput` with the session stopped afterwards;
turn failure propagates the typed error and still releases the session.

Local run: `uv run pytest packages/maistro-core/tests/capabilities/test_codex_app_server_harness.py -q`
→ 27 passed; `uv run ruff check .` and `uv run ruff format --check .` clean;
`uv run mypy packages/maistro-core/src` clean. The provider's public
`foreign_session_id` accessor is read by `send`/`stream` (not only by tests),
so the vulture per-identity ratchet (`packages/*/src --min-confidence 60
--exclude '*/third_party/*'`) reports no new debt for this change.
