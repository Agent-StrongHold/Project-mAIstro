---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# Issue 1085 Governed Hive Model Egress

Added focused tests covering the governed Hive model path:

- a successful model call creates an Invocation correlated to Run/NodeRun/Attempt and preserves usage/provider/model evidence;
- a gateway connection failure leaves the adapter failed and the Invocation failed rather than reporting compatibility success;
- the real Hive facade and canonical durable Run resolver preserve Attempt correlation while the governed caller outranks the legacy builder;
- clarify and grounded-search adapters forward model work through their supplied governed caller.
