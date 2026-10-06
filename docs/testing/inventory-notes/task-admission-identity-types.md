---
inventory-delta:
  packages/maistro-core/tests: +77
---

# #1851 root-admission identity types

This inactive #1845 leaf adds only
`packages/maistro-core/src/maistro/runs/admission_identity.py` and its focused
contract suite. It neither exports the module through `maistro.runs` nor adds a
production caller, RunStore change, task-idempotency change, SQL, or runtime
wiring.

`uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q -x`
collected and passed 76 cases. `uv run python scripts/check-suite-inventory.py
--suite packages/maistro-core/tests` collected 13,366 node IDs. The +76 delta
is the focused file, including the module-local export and enum-shape contract
check plus canonical JSON preservation of valid escaped lone surrogates and
normalization of excessive nesting failures to ValueError;
it is unchanged by unrelated test additions in the integration branch.

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

At verification head `0c384962ce867554b5d460f4fd43315120d36ba1`, the focused
suite passed 74 cases, module mypy passed, and the core suite inventory remained
13,364 node IDs (+74 for this file). Focused Ruff check and format check also
passed. The required exact Vulture command reported nine declarative identities
as new trusted-base debt (rc=1) against trusted base `8a4bc239fe9a`; that base
does not contain this module. The candidate ledger has the reviewed identities
as permitted by this CI-repair round, but candidate ledger edits cannot
authorize new debt under the trusted-base two-merge rule.

`check-reachability.py` likewise reported the deliberately unreachable
`maistro.runs.admission_identity` (rc=1). `check-reachability-dispositions.py`
and `check-promotion-surface.py` passed; `check-ratchet-provenance.py` failed
only because its reachability provenance sub-gate rejects that same new
unreachable module. These gates remain blocked until the separately authorized
parent integration supplies a real consumer or a prior trusted-base
authorization lands; this inactive leaf cannot repair them without violating
its scope.

## Current validation refresh

At `9ae7708432f276d22828682fcf52e842c0fa69e7`, the focused DTO suite passed
76 cases; `ruff check`, `ruff format --check`, and module `mypy` passed; the
Runs suite passed 1,199 tests (247 skipped); and suite inventory remained
13,366 node IDs (+76). The exact Vulture command still exits 1 only because
its trusted base `94781cf6b708` predates the nine reviewed declarative
identities already recorded in the candidate ledger. Reachability and ratchet
provenance also exit 1 only for this intentionally inactive module; disposition
and promotion-surface checks pass. Beyond the CI-repair-permitted Vulture
ledger entries, this leaf adds no reachability baseline, disposition,
suppression, or fake production import to evade that required integration-head
gate.

At evidence head `45476f48d1951c67c5f7fc2abcc1a71aa013a61c`, the focused
suite again passed 76 cases; focused Ruff check/format and module mypy passed;
and the core inventory remained 13,366 node IDs (+76). The required exact
Vulture command still reports the same nine candidate-ledger identities as new
against trusted base `94781cf6b708`; `check-reachability.py` reports only
`maistro.runs.admission_identity`; and `check-ratchet-provenance.py` fails only
through that trusted-base reachability gate. This inactive leaf cannot remove
those failures without the explicitly prohibited production consumer,
reachability ledger/disposition, suppression, or authorization grant.

## Current repair validation

At repair head `8b041d56be80bc288633c4648ccb1fb3b9e80afe`, the focused suite
passed 76 cases and the module passed Ruff check/format and mypy. The recorded
core suite inventory is now 13,727 node IDs; this suite's `+76` delta remains
unchanged. Validation confirms the module-local 21-name `__all__` contract
while retaining the repository's required sorted declaration order. The exact
Vulture and reachability gates remain blocked by the deliberately unwired
module (nine trusted-base
Vulture identities and `maistro.runs.admission_identity`, respectively), which
cannot be repaired in this leaf without violating its no-production-consumer
constraint.

## CI-repair validation

At CI-repair head `ee9481aec1520dea19427a2fe3f9d40483e4a4e4`, the focused
DTO suite passed 76 cases, the Runs suite passed 1,199 tests (247 skipped),
and module Ruff check, format check, and mypy passed. The core inventory
remained 13,727 node IDs, preserving this suite's `+76` delta.

The exact Vulture command reports nine declarative DTO identities as new
against trusted base `658a8f78c180`; all nine are already the reviewed entries
in the candidate `quality/vulture-baseline.json`, as permitted for this
CI-repair lane. The trusted-base two-merge rule therefore still rejects them;
a candidate ledger cannot authorize itself. `check-reachability.py` reports
only the deliberately unwired `maistro.runs.admission_identity`, while
`check-reachability-dispositions.py` and `check-promotion-surface.py` pass.
`check-ratchet-provenance.py` fails only through that unauthorized unreachable
module. No production import, reachability ledger/disposition, suppression, or
quality waiver was added because each is prohibited by this staged leaf's
scope; parent integration must provide the real consumer before it can pass
integration-head quality.

## 2026-10-05 CI-repair revalidation

At `9fd115b2dd07fc50990617cdcc8e45fc3e59bb7a`, focused Ruff check/format,
module mypy, and the 76-case DTO suite passed; the core suite inventory
matched 13,844 node IDs (`+76`). The exact Vulture scan found 1,351 findings
and no candidate-ledger delta, but returned 1 because all nine reviewed DTO
identities are absent from trusted base `c560d4ccad82`; the permitted candidate
ledger amendment cannot self-authorize that debt. `check-reachability.py` and
`check-ratchet-provenance.py` returned 1 solely for the deliberately unwired
`maistro.runs.admission_identity`; dispositions and promotion-surface passed.
A production import, reachability ledger/disposition, suppression, or grant
would violate this leaf's explicit staging constraint, so parent integration
remains required for mergeable integration-head quality.

## Verifier revalidation

At verification head `3854d8ba9ffed2afb9341e310b7e0e597fa99dcf`, the focused
DTO suite passed all 76 cases; focused Ruff check and format check passed; and
module mypy passed. The exact Vulture command found 1,352 findings with no
candidate-ledger bookkeeping delta, but failed against trusted base
`658a8f78c180` because the nine reviewed declarative DTO identities are not
authorized there. `check-reachability.py` failed solely for the deliberately
unwired `maistro.runs.admission_identity`; reachability dispositions and
promotion-surface passed. `check-ratchet-provenance.py` failed only because
that new unreachable module has neither a trusted-base authorization nor a
real runtime consumer. No prohibited import, suppression, reachability
baseline/disposition, or quality waiver was introduced; integration must supply
the real consumer before mergeability can be established.

## Latest validation

At `ebc8186443a105d6fd206eba3779a331e15096f4`, the focused DTO suite passed
76 cases; module Ruff check/format and mypy passed; repository-wide Ruff check
and format passed; and the core inventory exactly matched 13,727 node IDs
(`+76`). The exact Vulture command found 1,352 findings but returned 1 because
nine unavoidable declarative DTO identities are absent from trusted base
`658a8f78c180`; their candidate ledger entries cannot self-authorize that
trusted-base debt. `check-reachability.py` returned 1 solely for the inactive
`maistro.runs.admission_identity`; dispositions and promotion-surface passed.
`check-ratchet-provenance.py` returned 1 only through that reachability
provenance failure. This leaf cannot add a runtime consumer, reachability
ledger/disposition, suppression, or grant; parent integration must do so before
mergeability.

## Independent repair validation

At `46e342750e4db5bcfe1ad551448d51554ace2d43`, focused Ruff check/format,
module mypy, the 76-case DTO suite, and the core inventory check all passed;
the latter again recorded 13,727 node IDs (`+76`). The complete
`packages/maistro-core/tests` suite also passed (12,799 passed, 927 skipped,
1 xfailed). The exact Vulture command still failed only on the same nine
trusted-base identities, and reachability/provenance still failed only because
this leaf deliberately has no permitted production consumer. Reachability
Dispositions and promotion-surface passed. This is evidence of a staged DTO
leaf, not evidence that the required integration-head quality gate is green.

## Current repair evidence

Focused Ruff check/format, module mypy, and the 76-case DTO suite passed; the
core suite inventory remains exactly 13,727 node IDs (`+76`). The exact
Vulture command produced 1,352 findings with no candidate-ledger delta, but
exited 1 because all nine reviewed DTO field/enum identities are absent from
trusted base `658a8f78c180`. The candidate `vulture-baseline.json` already
contains those entries, as allowed by this CI-repair lane; the gate confirms
that a candidate ledger cannot self-authorize them.

`check-reachability.py` exits 1 only for the intentionally inactive
`maistro.runs.admission_identity`. Production-source search finds no import or
caller; the package initializer does not export it, and this change adds no
reachability baseline/disposition or Vulture whitelist. Reachability
dispositions and promotion-surface pass. `check-ratchet-provenance.py` exits 1
only through that untrusted reachability debt. A separately authorized parent
integration must add the real runtime consumer before the integration-head
gates can pass; doing so here would violate this leaf's explicit scope.

## 2026-10-05 final validation

At `7f66ab706fbb95158faa6979385c34853a0ad6f6`, focused Ruff check/format,
module mypy, and the 76-case DTO suite passed. The core inventory check matched
13,844 node IDs, preserving this suite's `+76` delta. A production-source
search found no import of `admission_identity`, as required for this inactive
leaf.

## Exact nested DTO type validation

The contract requires nested DTO and binding fields to use their exact declared
type or union. A subclass passes `isinstance` but is not the declared immutable
snapshot/identity type, so the constructors now reject it with `ValueError`.
`test_nested_dtos_require_exact_declared_types` covers every nested snapshot,
binding, ticket, record, and union position. This adds one collected node; the
suite delta is now `+77`.

The exact Vulture gate found 1,351 findings and reports the same nine reviewed
DTO identities as new relative to trusted base `c560d4ccad82`; candidate ledger
entries cannot self-authorize them, so it exits 1. `check-reachability.py` and
`check-ratchet-provenance.py` likewise exit 1 solely for the deliberately
unwired `maistro.runs.admission_identity`; reachability dispositions and
promotion-surface pass. No prohibited production import, suppression,
reachability baseline/disposition, or authorization grant was added. Parent
integration remains required before these integration-head gates can pass.

## 2026-10-06 repair validation

At `68f9ef00f6cac955838b97c0ea05fb3cf4bd582e`, the focused DTO suite passed
77 tests; focused Ruff check/format and module mypy passed. The exact Vulture
command still exits 1 against trusted base `c560d4ccad82` for the nine DTO
field/enum identities already present in the candidate ledger. Reachability
still reports only the intentionally inactive module, and ratchet provenance
fails through that reachability debt. This staged leaf has no permitted repair
for either trusted-base failure; parent integration must provide the real
consumer before integration-head quality can pass.

## 2026-10-06 independent CI-repair validation

At `b9b1891a13760ee5afc810e5f2c6f76f1df9b69b`, the focused DTO suite passed
77 tests and module mypy passed. The exact Vulture scan found 1,351 findings
but exited 1 only because all nine reviewed declarative DTO identities are
absent from trusted base `c560d4ccad82`; the candidate ledger already contains
those identities, and trusted-base provenance correctly refuses to let that
candidate amendment authorize itself. `check-reachability.py` exits 1 only for
the intentionally inactive `maistro.runs.admission_identity`; the dispositions
and promotion-surface gates pass. The full suite-inventory check matched all
15 suites (26,808 unique node IDs), including 13,845 maistro-core tests. The
provenance aggregate fails only at its reachability sub-gate for that same
unwired module. No Vulture whitelist, reachability baseline/disposition,
suppression, grant, or production import was added: each would violate this
leaf's staging constraint. Parent integration must add the real consumer before
integration-head quality can pass.

## 2026-10-06 verifier repair validation

At `7d0fc25b42b441762ff916c54a0ba631207b3077`, the focused DTO suite passed
77 tests; module Ruff check/format and mypy passed; and the core suite inventory
matched 13,845 node IDs (`+77`). The exact Vulture gate found 1,351 findings
and failed only because the nine reviewed DTO identities are not present in
trusted base `c560d4ccad82`; the candidate ledger already contains exactly
those identities. `check-reachability.py` and the provenance aggregate fail
only because the deliberately inactive `maistro.runs.admission_identity` has
no permitted runtime consumer. Reachability dispositions and promotion-surface
pass. Production-source search confirms no import, caller, package export,
whitelist reference, reachability baseline/disposition, or grant was added.
The remaining exact-debt failures require the separately scoped parent
integration to supply a real consumer or a prior trusted-base authorization;
this leaf cannot do either without violating its staging constraint.

## 2026-10-06 final repair validation

At `8f6956f23625463e8635d4a2ec0d7ce7579cfd91`, the focused DTO suite passed
77 tests; the complete `packages/maistro-core/tests` suite passed 12,906 tests
(938 skipped, 1 xfailed); focused and repository-wide Ruff checks/format checks
passed; module mypy passed; and the suite inventory matched all 15 suites,
including 13,845 core tests (`+77`). The exact Vulture gate remains blocked by
nine DTO identities absent from trusted base `c560d4ccad82`, while reachability
and ratchet provenance remain blocked solely by the intentionally unwired
`maistro.runs.admission_identity`; dispositions and promotion-surface pass.

## 2026-10-06 current validation

At `585f308378816f2860e67f75a737e06c7a5c724e`, the focused DTO suite passed
77 tests; focused Ruff check/format and module mypy passed; repository-wide
Ruff check/format passed; and the core suite inventory matched 13,845 node IDs
(`+77`). The exact Vulture gate still fails only because its trusted base
`c560d4ccad82` lacks the nine candidate-ledger DTO identities. The ledger
contains all nine reviewed identities, but the gate correctly refuses a
candidate ledger as trusted-base authorization. `check-reachability.py` reports
only the deliberately inactive `maistro.runs.admission_identity`; dispositions
and promotion-surface pass, while ratchet provenance fails only through that
unreachable module. A production-source search confirms no other production
module imports or calls the DTOs and no reachability baseline, disposition,
grant, export, or Vulture whitelist was introduced. Parent integration remains
required for mergeable exact-head quality.

## 2026-10-06 ledger repair

The exact Vulture scan at merge head `65f5376fae59` identified two stale
candidate-ledger entries for `format_version`; scanner output contains neither
identity. This repair prunes both entries. The candidate ledger now exactly
banks the seven scanner-reported DTO identities, but the exact gate still exits
1 because those identities are absent from trusted base `626683154ce9`; a
candidate ledger cannot grant itself authorization. The same head's focused
DTO suite passed 77 tests, the full core suite passed 13,383 tests (938
skipped, 1 xfailed), and full suite inventory matched 14,322 core test IDs
(the existing `+77` delta). `check-reachability.py` and the provenance
aggregate remain blocked solely by the intentionally unwired
`maistro.runs.admission_identity`; dispositions and promotion-surface pass.

## 2026-10-06 final local verification

At `74e9615351ccfd0c3c48d4c49c7fcce0938960de`, the focused DTO suite passed
77 tests; focused Ruff check/format and module mypy passed; and the core
inventory exactly matched 14,322 test IDs (`+77`). The exact Vulture scan
reported no candidate-ledger delta and exactly seven reviewed DTO identities,
but correctly failed because trusted base `626683154ce9` predates them.
`check-reachability.py` reported only the intentionally inactive
`maistro.runs.admission_identity`; dispositions and promotion-surface passed,
and the provenance aggregate failed only at that same reachability gate. This
leaf has no permitted runtime consumer, reachability ledger/disposition,
suppression, or grant; parent integration remains the required next step.
