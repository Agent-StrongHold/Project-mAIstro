---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/hive-conductor/backend/tests: +5
---

# Agent declaration narrowing at the shared tool boundary (#847, partial)

Six Agent.handle cases prove that empty, unlisted, differently cased and
alias-shaped declarations cannot be widened by a Sentinel grant; exact and
duplicate declarations preserve the existing dispatch identity contract.

Five boot-composition cases construct the real SQLite Container, factory,
Agent, Sentinel, persisted admission records and admitted tool executor. They
prove that ReAct, Artificer and BuildersLearning's reachable ReAct path cannot
invoke an unlisted model-backed tool, and that strategy-authored exposure
metadata cannot widen either the legacy callback or identity-aware hook.
HTTP is intercepted by MockTransport; no external provider effects occur.
The valid-grant fixtures fail against the previous implementation.

This is the declaration-narrowing portion of #847, following the existing
[Binding/Invocation authority](../../adr/ADR-081226-6b46-capability-provider-binding-invocation.md).
The existing Sentinel policy and persisted Binding admission still decide
whether a declared call may execute. This change does not replace them with
another authority service. #1540 remains a historical, broader salvage PR.

Remaining #847 work includes typed missing-schema denial, AgentSpec field
interpretation, command grammar and the legacy BuildersLearning Frank/Mason
reconnaissance methods. Agent.handle does not supply a worker selector, so
these tests do not claim those Frank/Mason methods are reachable from boot.
