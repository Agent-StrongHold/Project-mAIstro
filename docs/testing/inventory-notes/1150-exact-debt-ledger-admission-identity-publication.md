---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Issue 1150 CI-repair: publish the root-admission identity vocabulary to green exact-debt-ledger

## The red, and why it is not this issue's debt

The merge-queue `exact-debt-ledger` job runs three steps:

1. `scripts/check-ratchet-provenance.py`
2. `scripts/check-shipped-surface-truth.py`
3. `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

Steps 2 and 3 are green at this branch's head (the vulture half is green: the
branch's own refactor removed three genuinely dead `bind_workspace_store`
methods, and `quality/vulture-baseline.json` was amended to drop exactly those
three reviewed identities). Step 1 was red, but **not** on a ratchet this issue
moved: the `reachability` ratchet reported

```
- maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
- maistro.runs.admission_identity: current unreachable module missing from candidate baseline
```

`maistro.runs.admission_identity` is #1851's intentionally unwired contract
leaf. It landed on develop in `e20e9f52e` (merge of auto-1851) **without** a
reachability-baseline row and without a `quality/ratchet-authorizations.json`
grant, so every candidate cut from that base fails `check-reachability`
(169 unreachable of 1417 modules). The pre-existing debt was reproduced on a
detached copy of the base tree (same 169-vs-168 mismatch), so it is not debt
this branch introduced.

The two-merge rule closes the ledger side: `ratchet_provenance.load_authorizations`
reads grants from the merge base, so a branch-side baseline row or grant can
never authorize the new debt. A ledger repair is therefore impossible from this
branch.

## The repair: move the leaf on the tree side

When the leaf is reachable from an entry point there is no candidate debt to
authorize and no `quality/*.json` file has to move. `maistro.runs` already
publishes every other submodule of the canonical execution model this way
(`concurrency`, `eval`, `execution`, `lifecycle`, `model`, `reconciliation`,
`service`, `store`), so the package now publishes the #1851 identity vocabulary
too — `AdmissionBinding`, `AdmissionRecordV2`, `CanonicalJsonObject`,
`LegacyAdmissionRecord`, `RootAdmissionEnvelope`, declared in `maistro.runs.__all__`.
The submodule docstring is corrected (it no longer claims nothing in production
imports it; no production path *consumes* the types). The contract itself — the
DTOs, the fencing conjunction, "constructing a DTO is not admission" — is
untouched, and no authorization path changes.

This is the same tree-side repair sibling lanes #886 (`2d662ed43`), #948
(`8b5a2e838`) and #1859 (`43361b8ed`) carried for the identical inherited red;
the content is identical so the lanes merge without conflict.

## Tests (+3 inventory delta)

`packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py`
pins:

* `test_runs_package_publishes_the_admission_identity_names` — the published
  names are the module's own objects and are declared in `__all__`;
* `test_published_names_are_importable_with_a_from_import` — a downstream
  product can `from maistro.runs import ...` the vocabulary;
* `test_the_package_publication_is_the_only_production_edge` — the leaf keeps
  exactly one production edge (the package `__init__`), so the reachability the
  import graph reports is a published library surface, not a runtime consumer.

## Gate evidence at this head (`RATCHET_BASE_REV=origin/develop`)

* `check-ratchet-provenance.py` exit 0
* `check-shipped-surface-truth.py` exit 0
* `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1323 findings)
* `check-reachability.py` exit 0 (168 unreachable of 1417, was 169)
* `check-reachability-provenance.py` exit 0 (168 -> 168, no candidate-approved expansion)
* `ruff check .` / `ruff format --check .` clean
* `pytest packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py` 3 passed

No `quality/*.json` row, grant, or gate script is touched by this repair.
