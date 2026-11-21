---
inventory-delta:
  packages/maistro-core/tests: +5
---
# cursor-m1-b-p4b-reconciler-recovered-disposition-8551-2e2c

#232 P4b reconciler provenance: five new cases covering unknown CANCELLED
refusal (with/without caller RECOVERED), transitional unknown+REQUESTED
terminalize, conflicting caller cause, typed RECOVERED disposition
delegation, and typed REQUESTED terminalize. Spine rename of the old
"recovery is the default" case is net-zero.

## Verification evidence (repair round, head 70b1d7f7dab0)

Fail-before/pass-after for the two acceptance-named provenance tests:
re-introducing the pre-P4b implicit `CancellationCause.RECOVERED` fallback
(`cause = persisted.cancellation_cause or cancellation`) in
`_reconcile_cancelled` fails exactly
`test_unknown_cancelled_refuses_even_with_caller_recovered` and
`test_conflicting_caller_cause_refuses` (DID NOT RAISE RunIntegrityError);
HEAD content restored byte-identical (sha256 5200bb08b7d73a63) and the file
passes again. Gates re-run at head: targeted battery 441 passed;
`packages/maistro-core/tests/runs` 1614 passed; `graph/durable_runs` 846
passed; ruff check + format clean; CI-exact vulture ledger exit 0 (1229
identities). `pr-base` failure at head is the ADR-095 stacked-PR expectation:
`check-pr-base.py --base cursor/m1-b-p4a-recovered-disposition-8551` exits 1
with the retarget instruction while `--base develop` passes, so the gate
resolves at merge-time retarget and needs no code change.
