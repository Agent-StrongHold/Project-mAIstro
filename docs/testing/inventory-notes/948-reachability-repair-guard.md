---
inventory-delta:
  packages/maistro-core/tests: +3
---

# #948 (EPIC M9-J) — the reachability repair is pinned inside the package

The branch carries a CI repair (see
`948-public-proof-truth-pins.md`, "CI-repair round: reconnecting
`maistro.runs.admission_identity`"): `maistro/runs/__init__.py` re-exports the
five admission-identity names so the module is reachable from the package's
published front door, instead of being banked as unreachable debt in
`quality/reachability-baseline.json`.

That repair had no guard inside the package it protects. The gate
(`scripts/check-reachability.py`) is a *ratchet*: it compares the candidate
tree against the trusted base, so the day someone prunes the re-export, the
`exact-debt-ledger` job's `check-ratchet-provenance.py` step reds on whatever
PR happens to be open, with "NEW unreachable module absent from trusted base"
— and nothing in `packages/maistro-core` says which import disappeared. The
three pins below say it in one line, next to the surface.

**+3 `packages/maestro-core/tests/runs/test_public_surface.py`** (collect
verified; a new file, 3 collected node IDs):

- `test_admission_identity_vocabulary_is_importable_from_the_package_root` —
  the five published names are the module's own objects, not copies;
- `test_all_publishes_the_admission_identity_names` — importable is not
  published: `maestro.runs.__all__` is the surface contract, and a name that
  imports but is missing from `__all__` is a pruned surface;
- `test_the_admission_identity_module_is_reachable_through_the_package_root` —
  a **cold interpreter** that imports only `maistro.runs` can reach
  `maestro.runs.admission_identity`. In-process the first test to touch a
  package populates `sys.modules`, so an import that only works because
  something else imported it first looks fine; the ratchet's question is
  about a cold start, so the test asks it in a subprocess (the pattern
  `tests/runs/test_import_order.py` already uses).

**The pins are not vacuous.** With the re-export deleted from
`packages/maistro-core/src/maestro/runs/__init__.py` (reverted immediately
afterwards; the file is byte-identical to the committed one):

```console
$ uv run pytest packages/maistro-core/tests/runs/test_public_surface.py -q
FAILED ...::test_admission_identity_vocabulary_is_importable_from_the_package_root
FAILED ...::test_all_publishes_the_admission_identity_names
FAILED ...::test_the_admission_identity_module_is_reachable_through_the_package_root
3 failed in 1.83s
```

and with the re-export in place, `3 passed in 1.71s`.

## This round's independent diagnosis of the `exact-debt-ledger` failure

The lane brief attributed the failed `exact-debt-ledger` job to the *vulture*
per-identity ledger. The evidence says otherwise, so no `quality/vulture-baseline.json`
amendment was made — there is nothing unbanked to bank.

The job (`.github/workflows/vulture-ratchet.yml`) runs three steps in order:
`check-ratchet-provenance.py`, `check-shipped-surface-truth.py`, then
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'`. Reproduced at the PR head `22b675061` (worktree
`/home/dev/Git/worktrees/mq-948-22b675061`, `RATCHET_BASE_REV=origin/develop`
= the base the job names):

```console
$ uv run python scripts/check-ratchet-provenance.py
ratchet: reachability  [python import graph ...]
  baseline: base e20e9f52ea94
  candidate: 22b6750614ee
  168 unreachable modules  ->  169 unreachable of 1417 modules
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
  - maistro.runs.admission_identity: current unreachable module missing from candidate baseline
FAIL: ratchet provenance inventory is incomplete
  - check-reachability-provenance.py: trusted-base gate returned 1
                                                        # exit 1 — step 1 of 3

$ uv run python scripts/check-vulture-baseline.py packages/*/src \
    --min-confidence 60 --exclude '*/third_party/*'
ratchet: vulture  [vulture (tool version: 2.16), metric v1]
  baseline: base e20e9f52ea94
  candidate: 22b6750614ee
  1326 reviewed identities  ->  1326 findings            # exit 0 — step 3 of 3
```

The vulture step was green at the failing head; the *first* step failed, on
the reachability ratchet, over the module develop shipped in #1851 and never
banked. That is the hole the branch's re-export closes, and it is why
`quality/` on this branch is byte-identical to the base: banking the row
instead would need a grant that only a previously merged base can carry
(`ratchet_provenance.load_authorizations` reads
`quality/ratchet-authorizations.json` from the merge base — the two-merge
rule), and the grant-first merge cannot be landed from this lane.

With the repair in place, all three steps of the job are green at
`8b5a2e838`: `check-ratchet-provenance.py` exit 0, `check-shipped-surface-truth.py`
exit 0, and the named vulture command exit 0 with 1326 reviewed identities →
1326 findings and 0 unclassified.
