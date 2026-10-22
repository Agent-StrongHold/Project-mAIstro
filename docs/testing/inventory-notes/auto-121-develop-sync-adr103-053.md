---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---
# auto-121 develop-sync round: ADR-103 ladder adopted beside the M4-B epistemics, migration re-parent as 053

The previous block left a mid-flight merge of develop (29af8200e) into
auto-121 with nine unresolved conflicts; every driver check failed only
because the markers made the files unparseable. This round resolved all nine
semantically, merged the current develop tip (91996e192, no further
conflicts), and re-proved the gate battery — including the coverage gate that
named this branch. No tests were added or removed: the union keeps both
sides' nodes (the branch's #120/#121 delegations and durable-twin pins beside
develop's ADR-103 ladder and stage-history pins), so suite inventory is
unchanged against the recorded baseline (the checker reports every suite ok,
25378 unique identities).

## The nine conflicts, resolved as unions of both designs

- `types/memory.py`: one canonical `LearningStage` (develop's ADR-103
  docstring; default `MEMORY`) plus `LEARNING_STAGE_ORDER`, beside the
  branch's epistemic constants and `EpistemicType`. The `Learning` record
  carries both field sets: stage/validated_by/promoted_by and the #121
  epistemics (epistemic_type, confidence, applicability, reinforce/contradict
  counters, validated_at, supersedes/superseded_by).
- `lifecycle.py`: develop's ladder prelude (`plan_advance`, `StageTransition`,
  `InvalidStageTransition`) beside the branch's pipeline rules (floors,
  half-lives, supersede/absorb, effectiveness) and the evidence ledger; the
  duplicate `_STAGE_ORDER` map is deduplicated into `LEARNING_STAGE_ORDER`.
- `store.py` + `learning_contract.py` + `pg_learnings.py` +
  `sqlite_learnings.py`: union column set and union API — the ladder write
  path (`advance_stage`/`stage_history`, the append-only
  `learning_stage_transitions` twin) beside `list_ineffective` /
  `mark_anti_pattern` and the lifecycle columns.
- `promoter.py`: `_admit_validated` now walks the ladder rung by rung
  (MEMORY -> LEARNING -> VALIDATED -> REPERTOIRE) so fresh rows promote under
  the ADR-103 bottom-rung default; capture keeps anti-patterns at their
  captured stage (reclassification is not assertion).
- Tests: `test_durable_hybrid.py` keeps both sides' forwarding pins;
  `test_pg_learnings.py` expected-INSERT tuple unioned; branch tests that
  pinned the old LEARNING default (`test_gauntlet`, `test_lifecycle`
  TestStageLadder, `test_sqlite_learning_lifecycle` pre-ladder row) updated to
  the canonical MEMORY semantics; develop's `test_pg_learning_stage`
  stage-column pin moved to the union insert's column positions.
- Migration: develop claimed `052_learning_stage_ladder` (M4-B1, ADR-103), so
  the branch's lifecycle-columns migration is renamed
  `053_learning_lifecycle_columns` (`down_revision = "052"`), adding only the
  columns develop's 052 does not (its downgrade leaves stage/validated_by/
  promoted_by in place). The chain-tip pin walks to `053` and asserts
  `get_heads() == ["053"]`.

## Named gate results (CI's exact arguments)

- Coverage gate: publish-set floor measures **93% (>= 87)** from the unit +
  PostgreSQL producers combined (migrations suite against an unmigrated
  pgvector:pg17 database: 103 passed; persistence/runs/graph/projects/
  workspaces/scheduling/events/elevation legs: 4973 passed, 8 skipped; unit
  producers: 12095 passed, 785 skipped, 1 xfailed — the one failure,
  `test_an_unreachable_server_is_an_error_not_a_fallback`, is environmental:
  this WSL kernel blackholes closed ports, so the dial to 127.0.0.1:1 hangs
  past pytest-timeout instead of raising ConnectionRefused instantly as it
  does on CI). Diff-coverage gate (`scripts/check-diff-coverage.py
  coverage.xml --base origin/develop`): **ok** — every measured changed file
  at/above 90% lines / 80% branch arcs; the 12 exempt files are tests and the
  migration, by declaration.
- exact-debt-ledger (`check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`): exit 0, candidate
  banking exact (1342 reviewed identities -> 1341 findings, 0 unclassified).
- Adjacent ledgers: radon, reachability, reachability-dispositions,
  promotion-surface (+provenance), direct-effects, durable-table-inventory,
  ratchet-provenance, enumerations, contract-markers, convergence-matrix,
  credential-authority, doc-links, execution-lifecycles, image
  inventory/pins, model-egress, principal-identity, release-consistency,
  route-permissions, security-inventory, wiring-reads, workflow-inventory,
  workspace-retirement, backlog-consistency, suite-inventory (14 suites ok) —
  all exit 0. `mypy --strict packages/maistro-core/src`: 0 issues (after
  `uv sync --locked --all-extras`, the quality-gate job's dependency set).
  `ruff check .` / `ruff format --check .`: clean.
- Acceptance-state ratchet + mandate against origin/develop
  (`check-ac-state.py --run-tests --ratchet --mandate origin/develop`): debt
  counters on their ceilings/floors, 0 unproven criteria, 0 chain violations.
