---
inventory-delta:
  packages/maistro-core/tests: +7
---
# 970-sandbox-import-cycle

Regression test for the import cycle the M9-G2 isolation layer closed against
develop's ambient-credential surface. `maistro.sandbox.protocol` bound
`SandboxFence` at module scope, and `maistro.sandbox.fence` reaches
`maistro.runs.model`, whose package import wires
`runs.execution -> maistro.runtime -> maistro.extensions ->
extensions.isolation -> sandbox.protocol`. The cycle was invisible while every
caller entered through `maistro.extensions`; importing `maistro.sandbox` (or
`maistro.sandbox.credential_boundary`, which develop's rsi suite now does)
died with "cannot import name 'SandboxFence' from partially initialized
module" during the acceptance-state ratchet's test run.

Fix: `SandboxFence` is annotation-only in `protocol.py`, so its import moved
under `TYPE_CHECKING` (commit 1702c5be7), the same pattern `fence.py` already
uses for `ExecutionLease`/`RunStore`.

`packages/maistro-core/tests/sandbox/test_import_cycles.py` (7) follows the
subprocess method of `tests/runs/test_import_order.py`: each entry point
imports first in a fresh interpreter, so `sys.modules` cannot hide the defect.
Six import orders (the failing ones and the ones that always worked) plus one
behavior check that the deferred import did not cost `SandboxConfig` its
shape. Against the pre-fix tree 4 of 7 fail; with the fix 7/7 pass.
