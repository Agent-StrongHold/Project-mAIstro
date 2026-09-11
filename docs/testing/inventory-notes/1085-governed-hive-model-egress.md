---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
  packages/maistro-core/tests: +1
---
# Issue 1085 Governed Hive Model Egress

The Hive backend suite adds focused governed-egress coverage while obsolete direct-HTTP compatibility cases remain removed. The focused tests cover:

- a successful production-composed model call creates an Invocation correlated to Run/NodeRun/Attempt from an explicit Binding, carries settings-backed gateway configuration, and preserves usage/provider/model evidence;
- connection, timeout, and HTTP 500 gateway failures leave the adapter failed; connection failure is recorded as failed while dispatched failures remain explicitly unknown rather than reporting compatibility success;
- a real canonical Hive HTTP 500 run terminalizes its NodeRun and Run as failed while retaining the Invocation's explicit unknown outcome;
- the real Hive facade and canonical durable Run resolver preserve Attempt correlation while the governed caller outranks the legacy builder;
- clarify and grounded-search adapters forward model work through their supplied governed caller;
- operator-declared model Bindings bootstrap into the canonical effect context, while a missing node Binding fails closed.
