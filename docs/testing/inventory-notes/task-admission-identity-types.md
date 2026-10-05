---
inventory-delta:
  packages/maistro-core/tests: +74
---

# #1851 root-admission identity types

This inactive #1845 leaf adds only
`packages/maistro-core/src/maistro/runs/admission_identity.py` and its focused
contract suite. It neither exports the module through `maistro.runs` nor adds a
production caller, RunStore change, task-idempotency change, SQL, or runtime
wiring.

`uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q -x`
collected and passed 74 cases. `uv run python scripts/check-suite-inventory.py
--suite packages/maistro-core/tests` collected 13,126 node IDs. The +74 delta
is the new focused file, including the module-local export and enum-shape
contract check; it is unchanged by unrelated test additions in the integration
branch.

## Security-signature revalidation

The accepted #1841 final head is
`053f93969b4dd607ee64d271e9c8d91f13ececc1`. At that head,
`runs/store_boundary.py` has
`require_admitted_actor(actor_principal_id: str | None) -> str`; `RunStore`
retains `get_run(self, run_id: str, *, principal_id: str | None = None) -> Run
| None`, and `create_run` / `claim_run_by_effect` retain
`actor_principal_id: str | None = None` plus the admitted-actor guard. `Run`
continues to store and validate `actor_principal_id: str | None`. The inspected
files are unchanged from #1841's earlier source head
`c66c5c8f60135b0f8b6ed3d43fa116a15399237d`.

## Staging result

The DTO suite proves only representation and invariant behavior. It does not
prove atomic admission or activate #1845. The module is deliberately
unreachable until the separately authorized parent integration supplies its
real consumer. Accordingly, the required reachability and provenance gates are
expected to report the module as a new unreachable production module; no
reachability baseline, disposition, grant, fake caller, suppression, or waiver
is present in this leaf.

The explicit CI-repair instruction for this lane conflicts with the issue's
ordinary no-ledger rule only for Vulture: it requires the reviewed
per-identity `quality/vulture-baseline.json` entries for the nine unavoidable
`pydantic-declarative-field` findings. Those entries bank the actual scanner
output but cannot authorize new trusted-base debt; `check-vulture-baseline.py`
therefore remains blocked on the pre-existing two-merge provenance rule until
a separately reviewed authorization lands on develop or the parent wiring makes
the module reachable.

Evidence base: `928993dda1c958ada2e6f8e54b5e5c04bf86bf77`; final repair commit:
`aec772d4c3d01000ba83958431b859cf1bb3ac56`.

## Final validation refresh

In the worktree based at `33a84b04c08900f4a7fa7bbbffdac5922b8183ea`, the
focused suite passed 74 cases, the suite inventory collected 13,126 node IDs,
the exact module/type-shape probe passed, and ruff plus module mypy passed. The required exact
Vulture command reported the nine reviewed-but-new identities as trusted-base
debt (rc=1); `check-reachability.py` likewise reported the deliberately
unreachable `maistro.runs.admission_identity` (rc=1), and
`RATCHET_BASE_REV=928993dda1c958ada2e6f8e54b5e5c04bf86bf77 check-ratchet-
provenance.py` failed only its reachability sub-gate. These must remain blocked
until the separately authorized parent integration supplies a real consumer or
a prior trusted-base authorization lands; this inactive leaf cannot repair them
without violating its scope.
