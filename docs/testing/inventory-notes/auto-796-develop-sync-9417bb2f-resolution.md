---
inventory-delta:
  packages/maistro-core/tests: +0
---

# auto-796-develop-sync-9417bb2f-resolution

Repair round for #796 ([M7-A7] Map Evolve/RSI as consumers of the same eval; forbid a
second loop). The round merged `origin/develop`'s tip (`9417bb2f4ac`) into `auto-796`
and re-validated the M7-A7 contract on the merged head. **No test was added or removed
by this branch** — `packages/maistro-core/tests` keeps the `+7` recorded in
`m7-a7-eval-consumer-map.md`, and the tests the merge brings in are `develop`'s own,
carried by `develop`'s own note (`auto-1885-3733.md`).

## Why the sync was the fix

The merge-queue evaluation of `4231ab641f3a` reported seven red checks. Read from the
Actions job logs, six were one defect and the seventh was a dependency bump `develop`
had already landed:

- `Quality / Reachability`, `exact-debt-ledger`, `test` and `Coverage gate` all went
  red on `maistro.runs.admission_identity` being unreachable in a tree that was behind
  `develop`. `packages/maistro-core/src/maistro/runs/__init__.py` is the import edge
  that makes that module reachable; `e20e9f52ea94` (the tip this branch had synced to)
  did not have it, and `9417bb2f4ac` re-added it.
- `Supply chain (pip-audit)` went red on `aiohttp==3.14.3`
  (`CVE-2026-111064`, `GHSA-2g87-pp6c-29x5`, `CVE-2026-111063`); `develop` bumped the
  pin to `3.14.5` in the same commit. `security` is that workflow's aggregate.

Banking `maestro.runs.admission_identity` in `quality/reachability-baseline.json` would
have made the gate green by freezing a module `develop` had just made reachable — a
floor raise against the base, which the ratchet forbids. The sync is the repair, and it
carries no ledger edit (`git diff --numstat origin/develop...HEAD -- quality/` is empty).

## The merge

`35f5e170a4` — `Merge commit '9417bb2f4ac84447278639c9d8b747f6c8371970' into
auto-796`. Conflict-free; nothing hand-edited. The branch's delta against `develop` is
still the five issue surfaces, and the merge introduced no production-code delta
(`git diff --numstat origin/develop...HEAD -- 'packages/*/src'` is empty).

## Suite inventory

```
$ uv run python scripts/check-suite-inventory.py
ok: 21 suite(s) match the recorded inventory
Unique-evidence report (21 suite(s) collected):
  collected node IDs: 32394
  unique test identities (cross-suite): 32394
  duplicate evidence from copied test files: 0
  byte-identical test files: 0 group(s), 0 redundant file(s), 0 redundant bytes
```

## Local-only artifact caveat (not a defect, not a count change)

`scripts/check-ratchet-provenance.py` writes the **git-ignored, generated**
`quality/ac-state.json` (`.gitignore:81`) into the worktree. A root-suite run that
follows then sees an unclassified `quality/*.json` and
`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
fails. A CI checkout never has that file. The artifact was moved aside (preserved at
`/tmp/ac-state.json.generated-local`) before the final root-suite run; it is not a test
change and moves no count.
