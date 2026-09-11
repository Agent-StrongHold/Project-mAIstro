---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# M1 #1036 canonical Conductor Run inspection

The Conductor DAG-run inspection service now prefers the configured canonical
RunStore for list/detail reads and exposes canonical NodeRun/Attempt evidence.
The retained `DagRunStore` is only a UI event projection; its status and IDs
cannot override canonical Run truth. The control route requests cancellation
through `RunStore.transition_run`, so terminal state is derived by the shared
lifecycle rather than by a product-local flag.

The three tests prove canonical detail identity, a conflicting projection being
ignored, and canonical cancellation. The existing scope suite continues to
cover Workspace authorization and the standalone projection compatibility path
used when no canonical bridge is configured.
