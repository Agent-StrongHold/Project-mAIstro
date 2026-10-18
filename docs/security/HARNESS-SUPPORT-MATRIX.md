# Harness provider support matrix

**Status:** informational matrix for the `harness_runner` slot (SPEC-208,
ADR-101); preference rows are encoded in
`packages/maistro-core/src/maistro/capabilities/providers/codex_app_server.py`
(`PREFERRED_CODEX_PROVIDER`) and asserted in
`packages/maistro-core/tests/capabilities/test_codex_app_server_harness.py`.

Which foreign-harness provider implementations this repository ships, what each
one is for, and which is preferred per foreign harness. The distinction that
matters throughout: **a provider is a governed adapter under MAIstro's
orchestration authority, never a peer scheduler.** MAIstro owns Goal
reconciliation, Graph/Run/NodeRun/Attempt identity, authorization, Events,
credentials, and tool/effect policy; the foreign harness owns nothing but its
own disposable session/thread state.

## Codex

| Provider | Status | Transport | Notes |
|---|---|---|---|
| `codex_app_server` | **Preferred** | Codex App Server (headless JSON-RPC session/turn API) | `CodexAppServerHarnessRunner` (`capabilities/providers/codex_app_server.py`). Session/turn/stream/stop ride the `HarnessRunner` protocol inside the sandbox + Warden + Sentinel/ActionGate + Invocation envelope. Foreign session/thread ids are provider metadata only. |
| Codex CLI adapter | **Not shipped.** Reserved as an explicitly lower-tier *compatibility/fallback* for hosts where the App Server is unavailable | Interactive CLI/tmux control | If added, it must (a) register under a distinct provider name, (b) never become a second execution/scheduling authority, and (c) advertise its reduced capabilities truthfully (no session resume, weaker streaming projection) rather than impersonating the App Server tier. |

## Other foreign harnesses

| Provider | Status | Transport | Notes |
|---|---|---|---|
| `opencode` | Shipped | `opencode run --auto` per turn inside the sandbox (`capabilities/providers/opencode.py`) | Reference CLI adapter; each turn is a fresh non-interactive run, repo filesystem is the cross-turn state. |
| subprocess reference | Shipped | Template-driven command per turn (`capabilities/providers/subprocess_harness.py`) | Base class for CLI-style adapters. |

## Invariants every row must satisfy (issue #822)

1. The provider starts/uses/stops sessions only through the `HarnessRunner`
   protocol; a canonical Graph Node drives it via `HarnessNodeExecutor` →
   `HarnessSessionManager` (`Binding -> policy -> Invocation`).
2. MAIstro `Run/NodeRun/Attempt` identity stays authoritative; foreign
   session/thread ids appear only as provider metadata.
3. Stream events project into canonical observation; the foreign harness is
   never a MAIstro Event authority.
4. Restart/failure/cancellation project truthfully onto the owning
   NodeRun/Attempt — no fabricated successes.
5. The foreign harness cannot schedule unrelated MAIstro Goals/Runs and is not
   a peer of #804's Workspace Agent reconciler.
6. Broad service credentials are never injected into the foreign sandbox when a
   mediated typed capability can perform the action; only the provider's own
   scoped credential material crosses the VM boundary.
7. Tool/effect requests traverse the canonical Warden / Sentinel(ActionGate) /
   Invocation boundaries applicable to the action.
8. Provider/session state is disposable/recoverable — never a second durable
   Agent definition, memory store, Goal store, or execution history.
