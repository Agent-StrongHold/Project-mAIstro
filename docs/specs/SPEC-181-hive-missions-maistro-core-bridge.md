---
id: SPEC-181
title: Hive missions to maistro-core execution bridge
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-13
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-002
implements: []
related:
  - maistro-engine#SPEC-176
  - maistro-engine#SPEC-180
contracts:
  - boundary
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
---

# SPEC-181: Hive missions → maistro-core bridge (phase 2)

## Context

[SPEC-176](SPEC-176-hive-conductor-package.md) ships Hive Conductor with an **in-memory stub** API (`/v1/tasks` = missions). `maistro-server` exposes different **`/tasks`** semantics. Real “agent hive” work requires **delegation**, persistence, and auth.

## Decision (target)

- Map Hive **mission** lifecycle to **maistro-core** task runner / queue (or `maistro-server` HTTP) with an explicit adapter layer.
- Persist missions outside `stores.py`; align naming with [SPEC-180](SPEC-180-maistro-install-bootstrap.md) install outputs only where env/bootstrap intersects.

## Out of scope (this spec)

- Full implementation — tracked after SPEC-176 phase 2 prioritization.

## References

- [SPEC-176](SPEC-176-hive-conductor-package.md)
- [docs/install/USERS-AND-AGENTS.md](../install/USERS-AND-AGENTS.md)
