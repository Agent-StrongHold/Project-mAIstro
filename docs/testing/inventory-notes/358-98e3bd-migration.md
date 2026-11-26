---
inventory-delta:
  tests/: 0
---
# #358: preserve develop's learning and admission migrations

No collected test count change. The existing chain-tip regression now requires
one head, 056, after learning applicability (054) and admission generations
(055), and verifies both parent edges. The audit-index round-trip now starts
and ends at 055, retaining the assertion that admission-generation columns
survive the audit-index downgrade. The transactional downgrade test retains
its captured pre-downgrade stamp rather than hardcoding the former head.

This resolves incoming merge conflicts and the concrete duplicate-055 migration
collision, without renumbering landed develop revisions. Commands and outcomes:
`docs/testing/358-98e3bd-repair.md`.
