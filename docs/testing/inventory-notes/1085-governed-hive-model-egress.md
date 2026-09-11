---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# Issue 1085 Governed Hive Model Egress

The Hive backend suite moves by a net +1 collected node ID: focused governed-egress coverage was added while obsolete direct-HTTP compatibility cases were removed. The focused tests cover:

- a successful production-composed model call creates an Invocation correlated to Run/NodeRun/Attempt, auto-provisions its legacy Binding, carries settings-backed gateway configuration, and preserves usage/provider/model evidence;
- connection, timeout, and HTTP 500 gateway failures leave the adapter failed; connection failure is recorded as failed while dispatched failures remain explicitly unknown rather than reporting compatibility success;
- a real canonical Hive HTTP 500 run terminalizes its NodeRun and Run as failed while retaining the Invocation's explicit unknown outcome;
- the real Hive facade and canonical durable Run resolver preserve Attempt correlation while the governed caller outranks the legacy builder;
- clarify and grounded-search adapters forward model work through their supplied governed caller.
