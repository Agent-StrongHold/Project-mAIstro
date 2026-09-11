---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Issue 1085 Governed Hive Model Egress

The Hive backend suite moves by a net +1 collected node ID: focused governed-egress coverage was added while obsolete direct-HTTP compatibility cases were removed. The focused tests cover:

- a successful model call creates an Invocation correlated to Run/NodeRun/Attempt and preserves usage/provider/model evidence;
- a gateway connection failure leaves the adapter failed and the Invocation failed rather than reporting compatibility success;
- the real Hive facade and canonical durable Run resolver preserve Attempt correlation while the governed caller outranks the legacy builder;
- clarify and grounded-search adapters forward model work through their supplied governed caller.
