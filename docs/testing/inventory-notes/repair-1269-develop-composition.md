---
inventory-delta:
  formal/: +0
  packages/maistro-core/tests: +0
  tests/: +0
---

The develop merge carried the org-bound-global memory visibility rule from #1258,
while the formal isolation property still constructed GLOBAL memories without
passing the generated organization context. The property now exercises the same
organization-bound contract as `matches_scope`, preserving the security behavior
and preventing a false composition failure.

Suite-count deltas: this repair moves no collected node ID itself. An earlier
composition of this note, recorded against develop cdf7343d, absorbed that
base's then-unbanked trunk drift (core +9, tests/ -8) so the gate would measure
the composed tree. The rebase onto develop b542ef56 (which lands #1489 and
#1272 with their own ledger notes) makes trunk's population changes
self-recorded, so the absorbed values would double-count; they are re-composed
to zero here. The branch's only true delta — the duplicate-occurrence coverage
in `packages/maistro-core/tests` (+8) — is recorded in
`1059-occurrence-recovery.md`.
