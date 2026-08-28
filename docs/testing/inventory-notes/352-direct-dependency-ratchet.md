---
inventory-delta:
  tests/: +11
---

# #352 direct runtime dependency usage coverage

Adds eleven focused root-suite cases for the production direct-dependency ratchet: requirement normalization, static and literal-dynamic imports, test-only false positives, third-party distribution-to-import mapping, local workspace namespace mapping, missing disposition failure, reviewed non-import runtime dispositions, explicit pending-cleanup ownership, stale dispositions after direct use or dependency removal, and required category/owner/rationale metadata.

The gate covers `[project].dependencies` for every `packages/*/pyproject.toml`; optional/dev groups are intentionally outside this production-runtime check. Production Python under each package is scanned with AST imports while test, mutant, build, distribution, and virtual-environment trees are excluded. Local workspace distributions are mapped from checked-in package source roots so editable-install metadata cannot falsely report shared namespaces such as `maistro-core` as unused.

The ratchet is part of the existing `scripts/pip_audit_gate.py` supply-chain entry point rather than a new tooling module. This keeps both existing pip-audit workflows on one dependency-policy gate without changing the repository reachability/convergence matrix: the final probe remained at 978 production modules with 213 unreachable, and the 52-subsystem convergence check stayed current.

The reviewed baseline contains 15 pre-existing unimported direct declarations. Four are verified non-import runtime dependencies owned by #352: Conductor `python-multipart` and `uvicorn`, Canvas `asyncpg`, and Server `uvicorn`. Eleven are explicitly marked `PENDING_CLEANUP` and assigned to #514 rather than receiving fabricated runtime justifications. The ledger is bidirectional, so each disposition fails once its dependency disappears or becomes directly imported.
