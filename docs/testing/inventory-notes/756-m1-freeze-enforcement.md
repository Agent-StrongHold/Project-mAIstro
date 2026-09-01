---
inventory-delta:
  tests/: +38
---

# PR #756 no-new-islands enforcement coverage

PR #756 adds thirty-eight collected root tests to the existing #460 convergence-freeze suite. The original sixteen cases prove that an exception label without a complete plan fails, #460 reuses the existing #36 lifecycle/model-egress/import vocabulary, planted Run/model-egress regressions are detected by those authoritative gates, new Workspace/Event/Checkpoint authorities are rejected outside canonical owners, canonical owners may extend their own concepts, explicitly marked product-local projections remain legal, one valid canonical concept cannot launder a second invalid owner on the same class, the checkpoint universe being retired by #729 cannot regain authority under `maistro.events`, existing legacy debt is not recharged merely because its file changes, the pull-request template carries the required review/exception fields, both pull-request and merge-group events resolve the immutable event base SHA rather than a moving branch tip, and the direct Formal Conformance checker invocation can recover the reviewed exception plan from GitHub's pull-request event payload without workflow-specific policy duplication.

Eleven additional fail-closed cases cover malformed ownership tables, malformed exception-policy and ontology schemas, invalid Python input, supported and failed git-diff parsing, explicit exception-plan precedence, missing and malformed GitHub event payloads, non-object pull-request payloads, and pull-request body recovery. Two additional main-entrypoint cases prove that the checker reports every accumulated architecture failure and returns nonzero, while the clean path emits the success contract and returns zero. Nine focused branch-coverage cases exercise shared-owner filtering, authoritative-gate validation, production-path classification, git-diff pair handling and failure propagation, plus explicit, malformed, and pull-request-backed exception-plan recovery. These cases exercise the checker paths identified by the per-file diff-coverage gate without changing or exempting checker behavior.

The pre-existing #460 tests for subsystem growth/shrinkage, live candidate comparison, and shallow-clone base resolution are updated in place and do not add to this delta.
