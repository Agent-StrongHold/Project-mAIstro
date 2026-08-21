---
id: ADR-096
title: "Hive Conductor / maistro-server boundary"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-10
supersedes: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-10
  - status: Accepted
    date: 2026-06-10
---

# ADR-096: Hive Conductor / maistro-server boundary

## Context

Hive Conductor currently embeds a full `TaskRunner` and graph execution engine in
its backend, making it both a UI/BFF layer and a standalone execution engine. This
dual role creates confusion about where production execution lives and leads to
security-critical code (sandbox management, tool execution) being duplicated or
misplaced in the UI layer.

## Decision

- **maistro-server** is the canonical backend/control plane for production execution.
- **Hive Conductor** is a UI/BFF adapter — it translates user intent into
  maistro-server API calls, renders results, and manages session state.
- Hive Conductor does NOT own production task execution.
- Hive Conductor does NOT start a production TaskRunner.
- Hive Conductor calls maistro-server for real workflow execution.
- Hive MAY keep a demo/stub mode for local development, explicitly marked
  non-production (`HIVE_MODE=demo`).

## Consequences

- The Hive backend becomes thinner: chat UI, dashboard, session management, and
  a `MaistroServerClient` adapter for execution.
- Sandbox policy, tool execution, and the security boundary live exclusively in
  maistro-core/maistro-server, not in Hive.
- Production deployments require maistro-server; Hive alone is insufficient.
- Demo/dev mode (Hive standalone) is explicitly gated and never the default.

## Acceptance criteria

- [ ] Hive does not own production task execution
- [ ] Hive does not start production TaskRunner
- [ ] Hive calls maistro-server for real execution
- [ ] Hive demo/stub mode is explicitly marked non-production
- [ ] No sandbox policy code lives in hive-conductor for production paths
