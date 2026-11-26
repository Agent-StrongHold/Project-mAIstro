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

## Independent re-verification (head b404b1b61500) — NEEDS-REPAIR

Re-executed at this head: `tests/test_check_citation_status.py` 64 passed;
`tests/test_check_reachability.py` + `tests/test_m1_542_policy_coverage.py` 40 passed;
`check-citation-status.py` OK (0 exceptions, ledger intentionally empty);
`check-citation-status-provenance.py` OK (46 reviewed → 0 current, base 60862b6c5e);
`check-convergence-matrix.py` OK; `check-suite-inventory.py` OK (13 suites);
`ruff check`/`format --check` clean; mypy `packages/maistro-registry/src` clean. No closure
keywords in the PR body or branch commit messages. All removed matrix citations were confirmed
non-active targets (Proposed/Deprecated/Superseded).

The checker, its status-combination coverage, and the front-matter/matrix gates are sound. What
fails acceptance is the same corpus-honesty standard the second wave claimed to have swept clean:
its sweep pattern `ADR-* (specifies|mandates|says)` misses the verbs `requires`/`defines` and
`SPEC-*` targets. A broader sweep (active-source spec/ADR prose, verbs
specifies|mandates|says|requires|defines|governs, ADR and SPEC targets) finds four coordinates the
repair never reached — two of them documents this branch itself moved from `implements` to
`related` with the present-tense prose left intact and zero status language in the file:

- docs/specs/SPEC-254-shadow-git-workspace.md:45 "ADR-049 requires every agent edit …" — ADR-049
  is Deprecated (docs/adr/ADR-049-shadow-git-rollback.md:5); this branch moved ADR-049 from
  `implements` to `related` (diff vs 60862b6c5e), silencing the gate, and the file carries no
  "design context / not shipped authority" marking anywhere.
- docs/specs/SPEC-255-parallel-wave-fan-in.md:47 "ADR-052 requires intra-task parallel
  sub-agents …" — ADR-052 is Deprecated (docs/adr/ADR-052-parallel-agent-waves.md:5); identical
  front-matter-only move by this branch, no status language.
- docs/specs/SPEC-062126-d421-medley-import-sanitization-pipeline.md:44 "SPEC-005 specifies the
  publisher VC / signing / revocation trust chain" — SPEC-005 is Proposed
  (docs/specs/SPEC-005-clawhub-full.md) and sits in `related`; the file disclaims ADR-083 but not
  SPEC-005.
- docs/specs/SPEC-182-a2a-delegation-implementation.md:45 "ADR-058 defines one protocol …" —
  ADR-058 is Proposed; mitigated by the explicit disclaimer at :34 ("remains Proposed; … not
  shipped authority"), lower severity, but the verb list should still cover it.

These violate "Proposed/non-active decisions cannot silently govern shipped behaviour" and the
DoD line "historical citations … cannot be mistaken for normative" at exactly the laundering
shape the branch's own `test_proposed_related_design_is_marked_historical_not_governing`
docstring names. Repair: apply the established prose-disclaimer pattern to the four documents
(two unmarked, two partial), extend the existing parametrization over the new pairs, and widen
the recorded sweep pattern to include `requires|defines` and `SPEC-*` targets; run
`check-suite-inventory.py --update` rather than estimating the node delta.

## Resolution (wave 4, this branch)

Applied on this branch: all four documents now mark their non-active authority as retained
design context, not shipped authority (SPEC-254/ADR-049 and SPEC-255/ADR-052 are `Deprecated`
and assert `is Deprecated`; SPEC-062126-d421/SPEC-005 and SPEC-182/ADR-058 are `Proposed`), the
normative verbs are gone (`requires` → `proposed that`, `defines` → `sketches`, `specifies` →
lineage framing), and the parametrization was extended from 10 to 14 documents with a
`status_note` column and a forbidden-verb list widened to
`says|specifies|mandates|requires|defines|governs` (68 tests, all passing). The widened corpus
sweep now returns only the repaired documents; two residual candidates were inspected and
rejected as non-violations, with reasoning recorded in `auto-374-wave4.md`.
Re-validation at this head: `tests/test_check_citation_status.py` 68 passed;
`tests/test_check_reachability.py` + `tests/test_m1_542_policy_coverage.py` included in the
same run, 108 passed total; `check-citation-status.py` OK (0 exceptions);
`check-citation-status-provenance.py` OK (46 reviewed → 0 current); `check-suite-inventory.py`
OK (13 suites, +4 recorded by `--update`); `check-convergence-matrix.py`, `check-adr-index.py`,
`check-adr-status-language.py`, `check-model-egress.py` all OK; `registry lint . --strict`
407 files clean; `ruff check`/`format --check` clean; mypy `maistro-registry` clean.
