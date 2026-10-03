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

## Round 3 (956c95932 develop-sync head): stale-grant pruning

The develop sync that brought M7-A3's `EvalMethod` consumers eliminated the
debt behind 3 of the 18 vulture grants this branch carried
(`ScoringMethod.DETERMINISTIC` / `_MODEL_JUDGE` / `_HUMAN` — vulture's
name-based usage matching now sees those member names as used, so the
identities no longer appear in the scan). Commit 5f06b8ca9 pruned the
matching ledger rows; this round prunes the now-stale **grant** rows from
`quality/ratchet-authorizations.json` (18 → 15 vulture grants), edited
textually — a JSON round-trip of this file silently drops rows because it
carries duplicate top-level keys (`principal-identity`, `route-permissions`
×2), the same lossy-merge hazard the monorepo guide documents for
`quality/*.json`.

Verified against the live scan at this head: the candidate
`quality/vulture-baseline.json` rubric rows (15), the branch's vulture grants
(15), and the scan identities (15) are now three views of the same exact set —
no stale grants, no ungranted identities, candidate bookkeeping green. The
remaining gate failures at `RATCHET_BASE_REV=origin/develop` are exactly the
structural two-merge set documented above: 15 unauthorized vulture identities,
2 new unreachable modules, 2 new dispositions — each waiting on the same
driver-side grants-first PR, for which this branch's `quality/` edits are the
ready-made, scan-verified content.

## Round 4 (this head): genuinely dead identities eliminated, 15 → 13

Applied the CI-repair directive "fix what is genuinely dead": two of the 15
identities were not contract surface at all but unreviewed speculative
generality, and are now deleted at the source together with their ledger rows
and grant rows:

- `RubricStore.list_for_goal` — zero callers in `src/`, zero tests, and no
  acceptance criterion names it (the issue's read-side requirements are the
  per-revision reads and the Run binding, both kept and tested).
- `RubricRunBindingSemantic.recorded_at` — write-only (default_factory populates
  it; nothing in src or tests ever reads it), not part of the issue's binding
  contract (goal_id + Goal revision + rubric_id + Rubric revision).

`quality/vulture-baseline.json` lost the 2 matching rows and
`quality/ratchet-authorizations.json` the 2 matching grants (both edited
textually because of the duplicate-top-level-key round-trip hazard documented
above). The candidate ledger still matches the live scan exactly (zero
candidate deltas). Re-verified at this head: ruff check/format clean; canonical
mypy invocation clean; 180 passed / 26 skipped in `packages/maistro-core/tests`
(ontology + projects); suite inventory unchanged; `check-shipped-surface-truth.py`
exit 0; candidate-local `check-reachability.py` exit 0 and
`check-reachability-dispositions.py` OK.

The remaining failure surface at `RATCHET_BASE_REV=origin/develop` is exactly:

- 13 unauthorized vulture identities — 5 contract-named fields
  (`pass_value`, `fail_value`, `evidence_required`, `pass_threshold`,
  `authored_by`, all issue vocabulary), 3 pydantic validators enforcing
  required invariants (`_at_least_one`, `_pack_shape`, `_dimension_consistency`,
  each exercised via `ValidationError` in `test_rubric_model.py`), and 5 store
  acceptance-surface members (`RubricStore`, `update_dimensions`,
  `instantiate_from_catalog`, `record_run_binding`, `binding_for_run` —
  acceptance criteria 3, 4, and 8). None can be eliminated without breaking an
  acceptance criterion: any renamed or restructured equivalent is flagged
  identically, because a src-only scan cannot see test-only consumption, and
  the stop condition ("Do not score anything") forbids the first production
  consumers.
- 2 NEW unreachable modules + 2 NEW dispositions (`maistro.ontology.rubric`,
  `maistro.projects.rubric_store`), dispositioned CONNECT (#34) / LIBRARY in
  `quality/reachability-dispositions.json`. Faking reachability via a
  re-export would contradict those reviewed dispositions and erase #34's
  CONNECT record, so they are left as recorded.

Each of these rows needs the already-written grants to exist at the merge base
(grants-only PR on develop, then rebase) — no further change to this branch is
required for `exact-debt-ledger` to pass.

## Round 5 (c5d57d8b5 develop-sync head): base-relative re-proof on the new develop tip

The lane base moved to develop `15157c6f2` (WIP M3-B7, #1738 squash), so this
round merged `origin/develop` into the branch (merge `c5d57d8b5`, conflict
free). Per the monorepo quality-ledger hazard note, the merge was audited for
silent row loss: `git diff HEAD^1 HEAD -- quality/vulture-baseline.json`,
`... ratchet-authorizations.json`, `... reachability-baseline.json`, and
`... reachability-dispositions.json` are all empty (branch-owned rows intact,
vulture ledger still 1372 = 1359 base + 13 rubric), and the only quality file
develop touched (`frontend-typed-client-baseline.json`) merged to exactly
develop's version (`git diff HEAD^2 HEAD` on it is empty; this branch never
edited it).

New evidence this round — the trusted base itself is clean, so the red is
attributable to this branch alone:

- A throwaway worktree at develop `15157c6f2`, judged against its own parent
  `5765efce8` (push-event semantics for the develop tip):
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → exit 0 with `1359 reviewed identities -> 1359 findings`
  (no delta), and `check-ratchet-provenance.py` → exit 0 (all ratchets OK,
  181 unreachable / 181 dispositioned). Develop carries no pre-existing
  ledger drift; every `exact-debt-ledger` finding in this lane's evaluation is
  one of this branch's two-merge identities.
- Post-merge, at `RATCHET_BASE_REV=origin/develop` (merge base now
  `15157c6f2`): `check-vulture-baseline.py` → exit 1 on exactly the 13
  identities listed in Round 4; `check-ratchet-provenance.py` → exit 1 on
  exactly the 2 NEW unreachable modules + 2 NEW dispositions;
  `check-shipped-surface-truth.py` → exit 0. The candidate ledger still
  matches the live scan with zero bookkeeping deltas.
- Re-ran the dead-identity sweep the CI-repair brief asks for: of the 13, ten
  are referenced by name in the rubric tests and the 3 pydantic validators are
  pinned behaviorally (`test_scale_requires_numeric_or_pass_fail` →
  `_at_least_one`, `test_pack_provenance_requires_pack_id` → `_pack_shape`,
  `test_dimension_ids_must_be_unique` + `test_veto_ids_must_reference_dimensions`
  → `_dimension_consistency`). Nothing else is genuinely dead; there was
  nothing left to delete or prune this round.

Post-sync validation at this head: `ruff check .` clean, `ruff format --check .`
clean (2776 files), rubric suites 44 passed
(test_rubric_contracts.py + test_rubric_model.py + test_rubric_store.py),
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (12173).

The unblock is unchanged and now has a direct in-repo precedent: develop
commit `d7f7f6f81` ("chore(#1572): authorize the canonical Goal store's new
vulture identities (#1833)") is the grants-first authorization commit that
unblocked the Goal store — this issue's own #458 parent dependency — through
the identical two-merge situation. Landing the equivalent authorization for
the 13 rubric identities + 2 reachability modules + 2 dispositions (the
content already reviewed in this branch's `quality/` edits) on develop, then
re-evaluating this branch, is the driver-side action that turns
`exact-debt-ledger` green.
