---
inventory-delta:
  tests/: +1
---

# 858-turing-provision-reachability-root

## What moved

`tests/test_reachability_scanner.py`, one new test:
`test_turing_provision_cli_is_a_rooted_entry_point_not_baseline_debt`
(+1 node ID, no parametrization).

## Why

CI-repair for issue #858's `exact-debt-ledger` gate. The #858 branch introduced
`packages/maistro-turing/backend/provision.py` — the documented, operator-
invoked service-identity bootstrap (`python -m backend.provision`) — and, because
nothing in the import graph reached it, banked it as a new unreachable module.
That self-authored baseline growth is exactly what the ratchet provenance model
refuses to bless (`scripts/ratchet_provenance.py` reads ledgers at the merge
base; the two-merge rule means an in-branch grant cannot authorize in-branch
debt), so `check-ratchet-provenance.py` failed on
`@flat/maistro-turing-backend/provision` and the exact-debt-ledger job went red.

The repair roots `provision` as a declared entry point of the
`maistro-turing-backend` flat app in `scripts/check-reachability.py`, following
the existing `export_book` precedent ("a spawned script is still an entry point
the import graph can root"). The module becomes genuinely reachable, its stale
baseline entry is removed, and `maistro.security.secure_random` — whose only
in-graph importers were the unreachable `trust_boundary` and `provision` —
leaves the baseline with it. No ledger grant is added; the debt is eliminated,
not authorized.

## The test

Asserts on the real repository graph that the provision CLI is collected as a
module of the flat app, is in the seen set (rooted entry point), and that its
in-graph dependency `maistro.security.secure_random` is reachable through it.
Without the root, the first two assertions fail exactly the way the CI gate
did; the third pins the baseline shrink so the two ledger removals cannot be
reverted independently of the classification.

## Validation

- `uv run pytest tests/test_reachability_scanner.py -q`
- `uv run python scripts/check-reachability.py` (unreachable set matches the
  candidate ledger exactly: 188, no newly-unreachable, no newly-reachable;
  the provenance wrapper records the truthful decrease 189 -> 188 as OK)
- `uv run python scripts/check-ratchet-provenance.py`
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
