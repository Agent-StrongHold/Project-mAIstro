---
inventory-delta:
  packages/maistro-core/tests: +1
---

# Issue #1139 repair — cover the canonical composition's versionless-Warden refusal

The repair driver reproduced the CI coverage-gate failure at 2a0161b:
`packages/maistro-core/src/maistro/security/composition.py` line 39 — the
`raise RuntimeError("canonical Warden must identify its policy version")`
branch of `build_canonical_security_dependencies` — had its refusing arc never
executed, so the fail-closed startup guard on the one canonical security
composition was unproven dead code to the diff-coverage gate.

The added test pins that refusal: a Warden that cannot name its canonical
policy version cannot be handed to any application root, because every boundary
audit record derives `policy_version` from the detector (#1139 correlation
requirement). Hence `+1` collected node ID in `packages/maistro-core/tests`.
No Turing-package suites moved in this pass.
