---
inventory-delta:
  packages/maistro-server/tests: +1
---

Issue #953 (M9-B2) repair round: declares `extensions.py`'s route handlers as
the module's public surface and locks the declaration with a drift test.

`packages/maistro-server/src/maistro_server/api/extensions.py` gains the
a2a.py/canvas.py `__all__` convention: every `@router` handler is declared as
module public surface, which is what keeps the handlers out of the
`fastapi-route-handler` Vulture ledger instead of re-entering the dead-code
ratchet as unbanked debt (the exact-debt-ledger gate failed on exactly these
7 identities at head `d7f2c9ba5c91` because a same-branch ledger cannot
authorize new debt — grants only count from the merge base).

`test_extensions_api.py::TestPublicSurfaceDeclaration::test_all_covers_every_route_handler`
(+1, the canvas.py drift-test pattern) parses the module AST for `@router`
handlers and fails with an actionable message when a handler skips the
`__all__` declaration. Verified in both directions: passes on the real
module, and the assertion names a handler that is removed from `__all__` in
simulation. Companion (non-test) ledger edits in the same round, each
verified against its gate at this head:
`quality/vulture-baseline.json` −7 (the now-unused extensions identities),
`quality/shipped-surface-truth.json` +4 reviewed dispositions for the
mutating install-lifecycle routes, and complexity extraction in
`extensions/manifest.py` / `extensions/service.py` bringing both new C-grade
radon blocks back under the floor.
