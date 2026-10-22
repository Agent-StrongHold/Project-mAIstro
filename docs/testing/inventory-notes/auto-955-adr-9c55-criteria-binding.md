---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-955 — ADR-100526-9c55 acceptance-criteria binding (#955 repair round)

No new tests. This change binds eleven existing
`packages/maistro-core/tests/extensions/test_compat.py` cases to the five
acceptance criteria the ADR declares (`@pytest.mark.ac("ADR-100526-9c55/AC-N")`)
and adds the matching `## Acceptance criteria` section to
`docs/adr/ADR-100526-9c55-extension-contract-versioning-and-deprecation-policy.md`,
so the ADR→AC chain check (`scripts/check-ac-state.py`) can see the proof that
already existed.

## packages/maistro-core/tests (+0)

- Decorators only: collected count, node identities and file set are unchanged
  (`scripts/check-suite-inventory.py --suite packages/maistro-core/tests` still
  reports the recorded 14118 unique identities).
- The markers make the previously-invisible proof legible to the acceptance
  gate: negotiation with `__import__` banned (AC-1), explicit degradation of
  optional features (AC-2), actionable major/window failure reasons (AC-3),
  machine-readable deprecation status with future-major removal targets (AC-4),
  and independence from application versions and private module paths (AC-5).
- `--mandate` against the develop base confirms all five newly-claimed
  criteria sit at the `reachable` rung ("every criterion this change declares
  is proven"), and the design-coverage improvement is banked in
  `quality/ac-state-notes/auto-955.json` per the gate's own instruction.
