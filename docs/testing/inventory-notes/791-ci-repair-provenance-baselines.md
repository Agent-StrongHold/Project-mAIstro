---
inventory-delta:
  tests/: +4
---

# 791 CI repair — trusted-base provenance for the P0.1/P0.2 debt baselines

## Why

The exact-debt-ledger gate at the merge queue failed first in
`scripts/check-ratchet-provenance.py`: the merge-queue evaluation of this
branch surfaced develop's own `check-principal-identity.py` (P0.1) and
`check-route-permissions.py` (P0.2) reading their `quality/*-baseline.json`
comparison oracles from the candidate tree — exactly the
"measurement and oracle from the same commit" defect the provenance inventory
exists to reject (#542, #319). With the inventory red, the job never reached
the vulture step, whose candidate ledger had also drifted (develop's
`maistro.identity` refactor moved `from_mnemonic`/`derive_named`/`did_key`/
`mnemonic_words`/`zero` into `_crypto.py` and added `principal.py`, while the
ledger still recorded the old `__init__.py` paths).

## What changed

- `scripts/check-principal-identity.py` and `scripts/check-route-permissions.py`
  now judge NEW violations/gaps against the ledger at the merge base
  (`ratchet_provenance.resolve_baseline`) and keep the worktree copy only for
  bookkeeping (stale rows must be pruned). A candidate can no longer bless its
  own regression with a same-commit baseline row.
- `scripts/check-ratchet-provenance.py`: documented `CANDIDATE_AUTHORED`
  exceptions for the two reviewed per-route specification ledgers
  (`route-permissions.json`, `public-routes.json`) — the registries being
  validated describe the routes this tree ships, so a prior-tree oracle would
  predate them (same rationale as `check-shipped-surface-truth.py`).
- `quality/vulture-baseline.json`: candidate ledger re-banked from a real scan
  (`--update`) — 9 new-path identity entries + `principal.py` legacy-dict
  helpers + `__getattr__` banked, 6 stale `identity/__init__.py` rows pruned,
  the 18 rubric rows unchanged in content (restored to sorted position).

## New tests (`tests/`, +4)

- `tests/test_check_principal_identity.py` (+2): `audit()` reports current
  violations as NEW when the trusted base tolerates nothing (proving the
  judgment oracle is the merge-base ledger, not the worktree copy), and still
  prunes stale rows against the candidate ledger when trusted == current.
- `tests/test_check_route_permissions.py` (+2): the same trusted-judgment and
  candidate-bookkeeping split for the P0.2 route ratchet.

The stubbed provenance resolver is injected via the modules' `_provenance`
seam, so no git state is required by the tests themselves.

## Provenance note

The two reachability dispositions this lane's modules need
(`maistro.ontology.rubric`, `maistro.projects.rubric_store`) are granted in
`quality/ratchet-authorizations.json` per the repo's two-merge doctrine
(grants are read from the base revision), so the reachability provenance gates
pass once this branch is the trusted base — verified by running
`check-ratchet-provenance.py` and `check-vulture-baseline.py` with
`RATCHET_BASE_REV` pointed at this branch's tip.
