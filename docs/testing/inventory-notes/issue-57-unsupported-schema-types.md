---
inventory-delta:
  packages/maistro-core/tests: +19
---
# Issue #57: unsupported argument schema types fail closed

Seven adversarial cases exercise `GovernedToolExecutor.execute` with a registered
host-owned contract: an unknown type, empty/null type, unsupported union, malformed
type declaration, and unknown nested object/array types. Each must raise
`ToolArgumentError` before Binding lookup, provider execution or Invocation events.
A typo must not turn a host-owned schema into unrestricted model input.
Five root-schema cases cover the shared validator used by model-tool strategies
without constructing a `ToolContract`; the root must not skip type checks either.

Seven positive controls keep the supported JSON primitive/container types valid,
including deliberately open object/array values. This repair does not claim full
JSON Schema support: undeclared type constraints remain optional; declared types
outside the supported subset must be refused, not silently ignored.

Red/green validation and issue-level limitations are recorded in
`.cursor/context/repair-57-c0e0b6ff.md`.
