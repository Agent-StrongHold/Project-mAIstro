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

## Independent re-verification (head 040fda23e262) — NEEDS-REPAIR

Re-executed at this head: `tests/test_check_citation_status.py` 57 passed;
`tests/test_check_reachability.py` + `tests/test_m1_542_policy_coverage.py` 40 passed;
`check-citation-status.py` OK (0 exceptions, empty ledger); `check-citation-status-provenance.py`
OK (46 reviewed → 0 current); `ruff check .` clean. Live demos: Accepted→Proposed substrate
refused; Superseded target resolved to its active replacement (ADR-001 → ADR-095); supersession
cycle reported; contradictory forked replacements refused; 77 matrix governing refs all resolve
to active/superseded targets with 0 problems. No closure keywords in the PR body or branch commit
messages.

The checker, its parametrized status-combination tests, and the matrix corpus are sound. What
fails acceptance is corpus honesty, by the lane's own standard (the docstring of
`test_proposed_related_design_is_marked_historical_not_governing`: moving a governing citation to
`related` silences the front-matter check, so the prose must carry the status honestly). That
standard was enforced on exactly three documents (SPEC-070226-af02/ADR-066, SPEC-070226-2b70/
ADR-055, SPEC-062126-d421/ADR-083) while seven more specs received the identical front-matter-only
move (Proposed ADR out of `substrate`/`implements`, into `related`; each file has exactly one hunk,
confined to front matter) with the normative prose left intact and unmarked:

- docs/specs/SPEC-070226-6489-identity-lifecycle.md:33 "ADR-084 specifies identity lifecycle";
  :146-147 an AC-level behaviour requirement ("archive, never hard-delete — ADR-084 §4") citing
  the Proposed ADR normatively (docs/adr/ADR-084-identity-lifecycle.md:4 `status: Proposed`)
- docs/specs/SPEC-070226-82ea-builders-dag.md:35 "ADR-099 specifies a DAG-based orchestration"
  (ADR-099 Proposed)
- docs/specs/SPEC-070226-b234-events-triggers-reactor.md:40 "ADR-086 specifies a durable event
  log" (ADR-086 Proposed)
- docs/specs/SPEC-070226-b624-orchestrator-waves.md:42 "ADR-071 specifies SuperPlanner"
  (ADR-071 Proposed; source status In Progress — an active source)
- docs/specs/SPEC-070226-c4f8-hierarchical-orchestration.md:33 "ADR-101 specifies portability"
  (ADR-101 Proposed)
- docs/specs/SPEC-070226-cb8d-llm-provider-registry.md:36 "ADR-079 specifies a unified provider
  registry" (ADR-079 Proposed)
- docs/specs/SPEC-070226-fbe3-deployment-topology.md:30 "ADR-081 specifies production deployment
  topology" (ADR-081 Proposed)

These are the same laundering shape as the two findings this branch repaired, at other
coordinates: the gate reports the corpus clean while present-tense "specifies" prose on Proposed
decisions remains, violating "Proposed decisions cannot silently govern shipped behaviour" and
"historical citations cannot be mistaken for normative". The corpus test pins only 3 of the ~10
affected documents, so coverage looks broader than it is. Repair: apply the same prose disclaimer
pattern to the seven documents and extend the parametrized corpus test over them (no test-suite
node-count change if done by extending the existing parametrization's argument list: +7 collected
nodes against the current 3, net +4 — run `check-suite-inventory.py --update`, do not estimate).

## Resolution (this branch)

The repair above was applied on this branch: all seven documents now mark their Proposed ADR as
retained design context, not shipped authority (including the two extra normative citations in
SPEC-070226-82ea: "ADR-099 requires" → "the ADR-099 proposal requires", and the `gate_exhausted`
policy attribution), and the parametrization was extended from 3 to 10 documents (64 tests in
`tests/test_check_citation_status.py`, all passing). A corpus-wide sweep for
`ADR-* (specifies|mandates|says)` against active specs now returns only the repaired documents
plus SPEC-080126-3a7c (itself `Superseded` — a non-active source, exempt by design). The node-count
reconciliation (−1 + 7 = +6) and prose live in `auto-374-2bb3.md`.
