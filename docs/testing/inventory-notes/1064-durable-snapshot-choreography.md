---
inventory-delta:
  packages/maistro-evolve/tests: +4
---
# 1064-durable-snapshot-choreography

CI-repair round for the #1064 branch (`auto-1064`): the CI-exact vulture gate
exited 1 because the six store methods introduced by the #1064 replay work
(`export_genomes_snapshot`/`restore_genomes_snapshot`,
`export_cycle_markers`/`restore_cycle_markers`,
`export_snapshot`/`restore_snapshot`) had their only production callers in
`packages/hive-conductor/backend`, outside the `packages/*/src` scan glob, so
vulture read them as unused protocol-and-adapter-port debt that no in-branch
ledger amendment can authorize (grants are read from the merge base by
design). Repair: the export/restore choreography moved into the package that
owns the stores as `maistro_evolve/durable_snapshot.py`
(`export_domain_state`/`restore_domain_state`/`EvolveDomainExport`, deliberate
public API via `__all__`), the two Conductor seams now call it, and the six
ledger rows the refactor made visible were pruned from
`quality/vulture-baseline.json`.

`packages/maistro-evolve/tests/test_durable_snapshot.py` (new, 4 tests) pins
the moved choreography itself: (1) a full round-trip through the exact json
path a durable snapshot takes, asserting semantic equality of the whole domain
(signature, cycle markers incl. committed/faulted finalize markers, canonical
battle publication index); (2) restore replaces prior state and never merges,
so a recovered process cannot supplement the snapshot with fabricated or
stale domain state; (3) the partial-double tolerance (a store with the genome
export surface but no marker ledger) that the finalize capture seam relies
on; (4) malformed tournament snapshot version fails loudly instead of
silently half-restoring.
