---
inventory-delta:
  packages/maistro-core/tests: +54
---

# P1a Attempt cancellation-cause model (#1884)

Base: `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
Pre-change model blob: `0de6b8ed9dedc87d590b39019cb0b0431e6259a2`.
Candidate model blob: `f7edb60a91f9b5592e2b0dcd8cb0dc309a510e09`.

Adds 54 collected cases in `test_attempt_cancellation_cause_model.py`:
14 missing/null cases across all physical statuses, 14 typed-cause/status
cases, 13 invalid-wire cases, three assignment-freeze cases, one exact legacy
payload case, four retained-lease shapes, three nested-serialization cases,
one unchanged-lifecycle guard, and one public in-memory creation/claim guard.

The independently frozen legacy JSON was checked against the complete original
model file before testing the candidate. Both file copies were verified with
Git blob hashes. The new wrap serializer removes only an unknown cause; it
preserves other null evidence and uses the existing Pydantic v2 serializer API
rather than requiring a new Field exclusion parameter.

## Isolated preflight, not repository or persistence evidence

Python 3.13.5 / Pydantic 2.13.4: 52 pure model cases passed; the two lifecycle
and store cases were deliberately deselected because this environment has no
full repository checkout. The actual model file was loaded under its module
name; no substitute model implementation was used. GitHub Actions must still
run the complete repository and the two public-production-path guards.

The same isolated model suite against the pre-change blob failed 27 cases.
Mutating the candidate to default RECOVERED failed 16 cases; globally dropping
null payload values failed four; removing the non-CANCELLED rejection failed
12. Each mutation was separate and the fixed model was restored and rerun.

This is shape/default-invariance work only. No writer, cancellation default,
reclaim predicate, lifecycle store, reconciliation policy, SQL schema, activation
or rollout changes. Unknown historical payloads are not upgraded. Parent #232
and #1151, backend codec proof #1885, and later dedicated writers remain open.
