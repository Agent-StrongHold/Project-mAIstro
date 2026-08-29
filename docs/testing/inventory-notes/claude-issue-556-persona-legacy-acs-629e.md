---
inventory-delta:
  packages/maistro-core/tests: +9
---
# claude-issue-556-persona-legacy-acs-629e

Nine tests added across two new files, for two criteria of SPEC-081226-bb3a.
No test was removed and nothing here compensates for a deletion elsewhere.

**`tests/graph/test_legacy_import_provenance.py` (+6) — AC-10.** The criterion
is a Scenario Outline over two kinds, `agent` and `graph/workflow`, and only
the agent half held: `snapshot_to_template` projected a legacy DAG snapshot
into a `GraphTemplate` and recorded nothing about its origin. That was a
production gap, fixed here, so these tests are not only new coverage — the
marked body is parametrised over both kinds so a future third kind that
forgets provenance fails by being added to the list. The remaining four
bodies pin the properties that make the record useful rather than decorative:
`source_hash` digests the source and not the template's own content, a
changed source changes the digest, and the digest is taken over the snapshot
as received rather than after this projection splits its keys.

**`tests/personas/test_catalog_membership.py` (+3) — AC-8.** Adding or
removing a template from a Persona catalog must leave template content and
instantiated objects alone. It holds structurally — the catalogs are
identifier lists — so the marked test carries the structural assertion
alongside the behavioural one. Without that it could not fail: with no
template content on a Persona there is nothing for membership to reach, and
the behavioural half would pass unchanged against a Persona that had grown
content and started drifting from the registry.

Both markers are mutation-verified. AC-10 fails under the pre-fix state (the
graph/workflow projection recording nothing) and under a projection that
records an empty source name. AC-8 fails under a `Persona` that accepts extra
fields, which is what would let template content be attached without a
deliberate schema change.

One production module was added (`maistro/graph/import_provenance.py`), which
moves the CONVERGENCE-MATRIX "Graph execution" row `3/60` → `3/61`. It exists
rather than a third inline copy of the same provenance dict: the metadata key
was already declared twice, in `agents.recipes` and `agents.importers.base`,
with the same value and no shared definition. Both now import it, so two
copies that agreed by luck became one that agrees by construction.
