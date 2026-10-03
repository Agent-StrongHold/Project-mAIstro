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

## Provenance note (corrected in the 0b44c1087 develop-sync repair round)

The two reachability dispositions this lane's modules need
(`maistro.ontology.rubric`, `maistro.projects.rubric_store`) are dispositioned
in `quality/reachability-dispositions.json` and granted in
`quality/ratchet-authorizations.json` (`reachability` + `vulture` sections),
per the repo's two-merge doctrine.

An earlier version of this note claimed the gates were "verified" by running
them with `RATCHET_BASE_REV` pointed at this branch's own tip. That claim was
wrong: a self-referential base reads the oracle from the very commit under
judgement, so it cannot fail and proves nothing about CI (the resolver even
refuses a clean self-referential run outright; see
`ratchet_provenance._refuse_self_reference`). Live CI at 0adabd52 failed
`exact-debt-ledger` on exactly this.

Executed reality against the real trusted base (post-develop-sync merge
67168d862, base = origin/develop tip a2b95053a, PR/merge-queue semantics):

- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability-provenance.py`
  → exit 1: `maistro.ontology.rubric` and `maistro.projects.rubric_store` are
  NEW unreachable modules "absent from trusted base and not previously
  authorized" (181 → 183 unreachable).
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability-dispositions-provenance.py`
  → exit 1: the same two NEW dispositions "absent from trusted ledger and not
  covered by an already-landed reachability authorization".
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 1:
  candidate bookkeeping is clean (the 3 stale `ScoringMethod` enum rows were
  pruned — develop's M7-A3 `EvalMethod` consumers make vulture's name-based
  usage matching see them as used; the 15 remaining identities were already
  banked), but the 15 Rubric identities are "unauthorized" because
  `load_authorizations` reads grants from the merge-base commit, where they do
  not exist yet.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-shipped-surface-truth.py`
  → exit 0.

This is the two-merge rule working as designed (`ratchet_provenance.py::load_authorizations`):
"a new grant does not take effect in the change that introduces it". Same-change
grants are structurally invisible, so these gates cannot pass from this branch
alone. They pass once the grants land on the trusted base first (grants-only PR,
the `#1767` precedent that preceded `#1321`) or once this branch's merge is
itself the base (post-merge reconciliation, the in-file `#1310`/`#1194`
precedent notes). This lane is prohibited from GitHub mutations, so the
grants-first PR is a driver-side action.
