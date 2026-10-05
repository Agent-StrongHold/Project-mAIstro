---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---
# auto-121 develop-sync round: migration re-parent as 052 and ledger union

The previous block left a mid-flight merge of develop (eb36d8061) into
auto-121 with two unresolved conflicts; every driver check failed only because
the conflict markers made the files unparseable. This round resolved both
semantically, merged the newer develop tip (cf4a562b6), and re-proved the
gate battery. No tests were added or removed — suite inventory unchanged
(packages/maistro-core/tests at 12409 matches the recorded baseline; the
migration chain-tip pin asserts the same number of walk targets, renumbered).

## Conflict 1 — migration chain collision (two heads)

Develop inserted `049_design_artifact_versions` (#780) and renumbered
`design_creative_briefs` to `050` and `canonical_run_eval_scores` to `051`,
both re-parented down the linear chain. This branch's learning-lifecycle
columns — `051_learning_lifecycle_columns`, re-parented onto `050` in the
previous collision round — shared `down_revision = "050"` with
`051_canonical_run_eval_scores`, so `get_heads()` returned two revisions and
`test_there_is_exactly_one_head` (the guard that exists for exactly this
race) would have failed. Resolution follows the file's own documented pattern:
the branch migration is renamed `052_learning_lifecycle_columns` with
`down_revision = "051"`, restoring one linear head. The chain-tip pin
(`tests/migrations/test_capability_invocation_effect_index_migration.py`)
walks to `052`, asserts every revision 039–052 is on the chain, and pins
`get_heads() == ["052"]`, with the comment narrating both collisions.

## Conflict 2 — quality/ratchet-authorizations.json append/append

Both sides appended grants to the `vulture` section: this branch the four #121
reviewed-identity grants (OutcomeEvidenceGauntlet, ChainedGauntlet,
effectiveness, LearningLifecycleStore), develop the #1572/#1816/#364 grants.
Resolution is the union; a row-count diff against both parents confirms no
rows were lost from either side (286 + 295 → 323 unique identities) and the
file parses.

## Named gate results (CI's exact arguments)

- Validate ADR/spec front-matter: `pytest tests/tools/registry/
  tests/tools/test_lint_lifecycle.py packages/maistro-registry/tests
  --confcutdir=tests/tools -p no:cacheprovider` → 98 passed;
  `tools/lint_lifecycle.py` → clean (0 accepted);
  `maistro_registry.cli lint . --strict` → 425 files clean;
  `check-adr-index.py`, `check-adr-status-language.py`,
  `check-citation-status-provenance.py` → all ok.
- exact-debt-ledger (`check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`): candidate banking is
  exact (1358 findings, no candidate deltas), but 4 reviewed #121 identities
  remain unauthorized because `ratchet_provenance.load_authorizations` reads
  grants from the merge base (cf4a562b6) only — the two-merges rule. The
  grant rows exist on this branch; landing them in develop first is a
  GitHub mutation outside this lane's authority. Not fixable in-tree without
  deleting #121's deliverables or adding scanner-appeasing references.
- Adjacent ledgers after the merge: radon (145 = 145, 0 stale), reachability,
  promotion-surface, durable-table-inventory (86 tables) — all ok; ruff
  check/format, mypy (769 files), version consistency — all ok;
  packages/maistro-core/tests 11626 passed, 782 skipped, 1 xfailed.
