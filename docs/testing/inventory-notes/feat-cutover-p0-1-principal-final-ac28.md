---
inventory-delta:
  packages/maistro-core/tests: +17
  tests/: -13
---
# feat-cutover-p0-1-principal-final-ac28

## The mutation-operator provider's tests moved into the suite that measures it

`test_mutation_operator_provider.py` moved from the root dev-tooling suite
(`tests/`, not inventory-tracked) into `packages/maistro-core/tests`: +13
node IDs there, −13 here. Same tests, same assertions — only `ROOT`
(`parents[1]` → `parents[3]`) changed. The reason is the diff-coverage gate:
it scores every changed line under `packages/maistro-core/src/maistro`
against the producers that measure that tree, and the producer that measures
it runs `pytest packages/maistro-core/tests`. From the root suite these tests
exercised `maistro.mutation_operator_provider.py` for the reader but not for
the gate — 61 changed lines at 0% against a 90% floor, a gate structurally
red for a file whose behavior was fully pinned.

The same file gains 4 tests pinning the module's published-import contract
(`TestPublishedImportContract`): with cosmic-ray/parso blocked at the
meta-path finder, the module must still import and the provider names must
raise an `ImportError` naming the missing toolchain — the wheel-import
gate's `all` tier walks every shipped module, and cosmic-ray is installable
from no extra at all (the `test_extra_guard.py` mechanics, applied to the
cosmic-ray operator provider).

Also in this change: `mutation_operator_provider._is_docstring` was split
(`_string_statement` helper) to bring its complexity from C(11) back to B,
so the radon and xenon ratchets carry no new row for it.

