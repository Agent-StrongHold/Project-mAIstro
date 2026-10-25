---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---
# auto-121 develop-sync round: adopt M4-B4 ledger lifecycle, clear the two-merge debt by declaring the public surface

This round merged `origin/develop` (1e4933e2a) into auto-121 and resolved the
M4-B4 collision in place. No tests were added or removed: develop's
`test_lifecycle.py` (49 ledger tests, SPEC-283) and this branch's
`test_lifecycle.py` (23 pipeline tests, ADR-100126-8c2d) now live in one file
(72 tests = 49 + 23), and develop's new store point-read test survives adapted
to the async `get` both suites already pinned. The delta above is therefore 0
on every suite, and all 14 suites re-verified against the recorded inventory
after the merge.

## Collision resolution (semantic, not textual)

- `memory/learnings/lifecycle.py` (add/add): develop's `InMemoryLearningLifecycle`
  evidence ledger (#120, SPEC-283) is the canonical ledger half; this branch's
  pure pipeline transitions (stage ladder, epistemic decay floors, row-level
  supersession/absorb, `effectiveness`) are appended as the second layer. The
  store-import moved under `TYPE_CHECKING` so the two halves do not import-cycle
  through the package `__init__`. `InMemoryLearningLifecycle`'s three
  `self._store.get(...)` call sites await the store's point read, which is async
  on this branch (org-scoped, `LearningLifecycleStore`-shaped).
- `memory/learnings/store.py`: develop's synchronous `get` (added in the same
  region git could not merge) was dropped in favour of the async org-scoped
  read both the lifecycle store tests and the protocol pin; its dedup-orphan
  rationale moved into the surviving docstring.

## Ledger deltas (the two-merge block, resolved by shrinking debt)

The previous rounds' BLOCKED verdicts traced to one root: the branch granted
its own new vulture/reachability rows in `quality/ratchet-authorizations.json`,
and `ratchet_provenance.load_authorizations` reads grants from the merge base
only — a grant never authorizes the change that introduces it. This round
removes the need for the grants instead:

- `memory/learnings/__init__.py` now declares the package's importable public
  surface via `__all__` (`ChainedGauntlet`, `InMemoryLearningLifecycle`,
  `OutcomeEvidenceGauntlet`, `effectiveness`) — the same declaration develop
  already made for `InMemoryLearningLifecycle`, and what ADR-100126-8c2d always
  claimed these were: embedder-facing API. The reachability graph follows the
  re-export (reachable package `__init__` → reachable `gauntlet`), so
  `maistro.memory.learnings.gauntlet` leaves the unreachable set (175 → 174,
  identical to base).
- `protocols/__init__.py` re-exports `LearningLifecycleStore` beside the other
  memory protocols, its established DI-surface pattern.
- Consequence rows pruned: the four vulture identities and the gauntlet
  reachability row leave `quality/vulture-baseline.json` /
  `reachability-baseline.json`; the four vulture grants and the reachability
  grant leave `quality/ratchet-authorizations.json`; the gauntlet CONNECT
  disposition leaves `reachability-dispositions.json`. Ratchets moved down,
  not sideways: vulture 1345 (base) → 1344 findings, reachability 174 → 174,
  dispositions 174 → 174, radon 145 → 145.

Gate proof at the merge commit: exact-debt-ledger and
check-ratchet-provenance (including both reachability provenance twins) pass
for the first time on this branch; Registry CI's seven steps, mypy --strict,
radon, promotion-surface, durable-table inventory (86 tables), release/doc
checks and all 14 suite inventories pass.
