---
inventory-delta:
  tests/: +24
---

Issue #374 adds three root-suite checks for the governing-citation ratchet's
second corpus: the convergence matrix. They cover a Proposed matrix authority,
an explicitly historical supersession note, and a Superseded authority resolving
to its active replacement. The checks share the registry status graph rather
than maintaining a second citation policy.

The recorded net delta is +24: +1 is this repair's historical-context regression,
+1 is the parenthetical-followed-by-governing-authority regression, while +22 covers
the existing status-graph and matrix coverage whose collected node IDs were not fully
represented by the earlier #374 note. The value was produced by `check-suite-inventory.py
--update`, not estimated from `def test_` counts.

## Independent verification (head 8bfd745ace5c)

Read-only re-verification of the lane at the merge head: `tests/test_check_citation_status.py`
57 passed; `tests/test_check_reachability.py` + `tests/test_m1_542_policy_coverage.py` +
`tests/test_ratchet_provenance_integration_base.py` 55 passed; `check-citation-status.py` OK
(0 exceptions, ledger intentionally empty); `check-citation-status-provenance.py` OK
(46 reviewed → 0 current against base 750edd84d); `registry lint --strict` 407 files clean;
`ruff check`/`format --check`, `check-adr-index`, `check-adr-status-language`,
`check-model-egress`, `check-suite-inventory`, `verify-monorepo-layout` all OK; mypy registry
clean. Live negative demo confirmed the checker refuses Accepted→Proposed substrate, names the
active replacement for Superseded targets, refuses contradictory forked replacements, reports
cycles, and exempts `related`. Matrix rows only dropped citations to Proposed/Deprecated/
Superseded authority (ADR-083, ADR-059, ADR-084, ADR-052, ADR-099, ADR-079, ADR-047, ADR-081,
ADR-101, ADR-082226-f436, ADR-070426-ac56, ADR-070426-e8a3, ADR-082226-d3dd, SPEC-010,
SPEC-011); kept citations are Accepted/Implemented. No closure keywords in PR body or commit
messages. No tree changes were required; this note is the only edit.
