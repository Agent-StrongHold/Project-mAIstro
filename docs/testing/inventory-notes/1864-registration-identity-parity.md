---
inventory-delta:
  packages/maistro-core/tests: +62
---

# 1864-registration-identity-parity

Issue #1864 adds a statically derived registration-identity layer beside the
existing composition guards, as a new suite file in the same directory:
`packages/maistro-core/tests/graph/nodes/test_production_registration_universe.py`
(+62 collected node IDs, all under `packages/maistro-core/tests`).

What moved and why:

- **The new file** proves, per acceptance criterion, that every reachable
  source registration expression the reachability universe ships is bound in
  the loaded registry to the actual defining class, module, and checkout file
  (`verify_identity_parity` checks registry membership, class name,
  `__module__`, and the methods' compiled filenames). A fresh-process probe
  inside the suite demonstrates the #1082 selection hole executed: a
  core-only load fails the proof for the reachable design registrations while
  the real production loaders pass. Negative cases cover substituted classes,
  spoofed modules, wrong source files, and the fail-closed diagnoses for
  registration forms the extractor refuses (dynamic arguments, qualified and
  star-import registrar access, re-export chains, nested deferred
  registration, ambiguous loop bindings, non-literal kinds, dynamic loop
  iterables). Shipped positive forms are attributed exactly: decorators,
  relative imports, aliased imports, literal loops over tuples and
  module constants, and direct calls kept separate from loops.
- **No existing count moved.** `test_node_composition.py` and
  `test_container_node_composition.py` are byte-identical to their previous
  state — this change deliberately does not narrow the broader non-`test.*`
  guard coverage; the new file asserts the derived minimum is a subset of it
  and reports extras separately. `test_production_registration_universe.py`
  itself is likewise new in this change (it did not exist on the base);
  prior rounds' partial work on it is subsumed here.
- Two existing assertions in the new file import the guards' own sweep
  functions (`shipped_kinds`, `_kinds_declaring_authorities`) to prove the
  sweeps and the reconciled universe agree — cross-file, so neither guard
  can silently shrink without failing here.

The fresh-process probe and parity assertions execute under the existing
core CI selection (`uv run pytest packages/maistro-core/tests --timeout=30 -q`;
the `graph` partition of it is the suite these files live in).

Collection verified via `scripts/check-suite-inventory.py --suite
packages/maistro-core/tests --update`.
