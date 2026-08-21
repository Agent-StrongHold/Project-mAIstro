---
id: SPEC-013
title: "1kHz reactor loop — event-driven runtime, replaces 30-min heartbeat"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-038
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-013: 1kHz Reactor Loop

See `blakematthews-dev/project_maistro` specs/conductor/S-143-1khz-reactor.md for full spec.

## Acceptance Criteria

- [ ] Reactor loop wakes within 5ms p95 of an event becoming ready
- [ ] All existing heartbeat behavior works as a `wall-clock-tick:30m` event source on the reactor
- [ ] Quiescent CPU usage < 1% on a typical desktop
- [ ] Multiple event sources can fire concurrently without race conditions
- [ ] Each source declares its capability-envelope policy at registration; spawner uses that policy to construct the AgentSpec
- [ ] No event source bypasses the Bouncer; every event payload is screened before the handler runs
- [ ] All state mutations from handlers go through `state.submit()` (SPEC-010); no direct write-mode SQLite connections
- [ ] Reactor handlers cannot block the loop — long-running handler work is offloaded to a worker pool; handler return must be ≤5ms p95
- [ ] Telemetry: per-source event count and latency visible in the Console
- [ ] Failing handler does not crash the reactor; reactor logs the error and continues
- [ ] SIGTERM shutdown: reactor stops accepting new events, drains in-flight handlers within a configurable grace period (default 5 s), cancels remaining work and rolls back any partial state writes, then runs a WAL checkpoint (SPEC-010) before exit
- [ ] Backpressure: when `state.submit()` queue depth exceeds the configured limit (default 10,000 items), the reactor pauses event delivery from the highest-volume sources rather than dropping events; handlers unable to submit state within the backpressure timeout (default 1 s) emit a `REACTOR_BACKPRESSURE_EVENT` alert
