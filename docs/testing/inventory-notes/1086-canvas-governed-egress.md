---
inventory-delta:
  packages/hive-conductor/backend/tests: +27
  packages/maistro-core/tests: +2
---

# Issue #1086 governed Canvas model egress coverage

The Canvas route tests exercise the shipped route's composition fallback with
canonical Run/NodeRun/Attempt state and verify that provider refusal settles the
owning Attempt instead of returning a score-shaped success. They also cover
successful Attempt settlement with parsed quality evidence and malformed provider
responses failing the owning Attempt after the Invocation completes. Adapter
coverage proves that Hive production settings carry provider metadata and explicit
model Bindings into the canonical maistro-core Container.

The verifier-repair pass widened the same suites (CI diff-coverage floor): route
refusals for foreign-owned or principal-less Runs, missing quality
Node/NodeRun/Attempt state, uncomposed or incompletely composed model egress, and
the trusted execution-context resolution path (supplied node/NodeRun/Attempt
identity, run mismatch, deployment-scoped Binding selection, and the stable
unconfigured-Binding reference). Unit legs pin `CanvasModelEgress`'s truthful
refusals (missing store/chain/context identity, cross-chain and scope mismatches,
terminal Attempt), `build_canvas_model_egress`'s SecretStr/plain key handling,
the Canvas score-parsing contract, and the hill-climb pass crossing the governed
seam. maistro-core gained the `ModelBindingConfig` validator refusal tests
(blank scope identity, empty credential/policy refs).
