---
inventory-delta:
  packages/maistro-core/tests: +65
---

# 1864-registration-identity-parity

Issue #1864 adds a statically derived registration-identity layer beside the
existing composition guards, extending the existing suite file in the same
directory:
`packages/maistro-core/tests/graph/nodes/test_production_registration_universe.py`
(+65 collected node IDs net, all under `packages/maistro-core/tests`).

What moved and why:

- **The identity layer** proves, per acceptance criterion, that every reachable
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
- **Review-round additions (all three verified to fail against the
  pre-review extractor, then pass with it):**
  (1) a registrar call hidden inside an unrelated statement call
  (`consume(register_node(A))`) now enters the universe and fails closed —
  previously the module silently dropped out of the scan entirely;
  (2) the expected minimum excludes ledgered-unreachable registration
  modules, mirroring `_import_reachable_registrations`' loading rule, so a
  reviewed exclusion cannot contradict the module-set equality or registry
  parity;
  (3) the ambiguous-loop diagnosis only considers loops whose bindings
  participate in a registration — unrelated loops reusing a target name no
  longer fail inventory construction.
- **No existing count moved.** `test_node_composition.py` and
  `test_container_node_composition.py` are byte-identical to their previous
  state — this change deliberately does not narrow the broader non-`test.*`
  guard coverage; the file asserts the derived minimum is a subset of it
  and reports extras separately.
- **Provenance:** `test_production_registration_universe.py` predates this
  change — it exists on the develop base `b1fc9a544f` with 14 collected
  tests from prior rounds' partial work. This change extends it in place
  (net 14 → 79); every prior round's test continues to run unrenamed.
- Two existing assertions in the file import the guards' own sweep
  functions (`shipped_kinds`, `_kinds_declaring_authorities`) to prove the
  sweeps and the reconciled universe agree — cross-file, so neither guard
  can silently shrink without failing here.

The fresh-process probe and parity assertions execute under the existing
core CI selection (`uv run pytest packages/maistro-core/tests --timeout=30 -q`;
the `graph` partition of it is the suite these files live in).

Collection verified via `scripts/check-suite-inventory.py --suite
packages/maistro-core/tests --update`.
