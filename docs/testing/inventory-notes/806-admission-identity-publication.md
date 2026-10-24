---
inventory-delta:
  packages/maistro-core/tests: +3
---

# 806 — publish the admission identity vocabulary to close the inherited reachability hole

This note records the CI-repair change that greens the `exact-debt-ledger`
gate for the #806 branch after its develop sync. It is a *tree-side* repair,
not a ledger edit: no `quality/*.json` row, grant or gate script moves.

## The failure (reproduced firsthand)

At the assigned head the exact-debt-ledger job failed. Re-deriving each of
its three steps with `RATCHET_BASE_REV=origin/develop`:

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — **exit 0** (1326 reviewed identities -> 1325
  findings). Already fixed by the previous #806 vulture round
  (`0fbd58674`).
- `check-shipped-surface-truth.py` — **exit 0**.
- `check-ratchet-provenance.py` — **exit 1**, solely via its reachability
  leg:
  `maistro.runs.admission_identity: NEW unreachable module absent from
  trusted base and not previously authorized`.

`check-reachability.py` confirmed the underlying fact: `1422 production
modules, 169 unreachable`, with exactly one newly unreachable module,
`maistro.runs.admission_identity`.

## Why a ledger edit cannot close it

`load_authorizations` reads grants from the merge base, so a branch-side
baseline row or grant is inert (the two-merge rule). The inherited debt is
real: develop `e20e9f52` landed #1851's contract leaf unbanked, so every
develop-based candidate carries `current - trusted = {admission_identity}`.
The tree-side repair is the only in-branch fix: when the module is
reachable from an entry point there is no candidate debt to authorize and
no `quality/*.json` file has to move.

## The change

`maistro.runs` already publishes every other submodule of the canonical
execution model (`concurrency`, `eval`, `execution`, `lifecycle`, `model`,
`reconciliation`, `service`, `store`). The package now also publishes the
root-admission identity vocabulary:

- `packages/maistro-core/src/maistro/runs/__init__.py`: imports and
  declares in `__all__` `AdmissionBinding`, `AdmissionRecordV2`,
  `CanonicalJsonObject`, `LegacyAdmissionRecord`, `RootAdmissionEnvelope`.
- `packages/maistro-core/src/maistro/runs/admission_identity.py`: the
  module docstring no longer claims "Nothing in production imports it yet";
  the contract (DTOs, fencing conjunction, "constructing a DTO is not
  admission") is untouched.
- `packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py`
  (3 node IDs): pins that the published names are the module's own objects
  and declared in `__all__`, and pins that the leaf stays a leaf — the
  package `__init__` is the only production edge, so the reachability the
  import graph reports is a published library surface, not a runtime
  consumer.

Sibling lanes #886 (`2d662ed43`) and #948 (`8b5a2e838`) applied the
identical change for the same inherited red.

## Evidence at this head (`RATCHET_BASE_REV=origin/develop`)

- `check-reachability.py` — **exit 0** (`1422 production modules, 168
  unreachable`; was 169).
- `check-ratchet-provenance.py` — **exit 0** (reachability leg `168 -> 168`,
  every other ratchet unmoved).
- `check-reachability-dispositions.py` — **exit 0** (48 groups cover all
  168).
- `check-shipped-surface-truth.py` — **exit 0**.
- `check-vulture-baseline.py` (CI-exact argv) — **exit 0** (`1326 -> 1325`;
  the `__all__` re-exports add no identities).
- `pytest packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py`
  — 3 passed.
- file-scoped `ruff check` / `ruff format --check` — clean.

`git diff --numstat origin/develop -- quality/` is empty: no ledger moved.
