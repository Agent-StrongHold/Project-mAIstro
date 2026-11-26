---
inventory-delta:
  packages/maistro-design/tests: +11
  packages/hive-conductor/backend/tests: +4
---

# 775-creative-graph-repair — issue #775 repair: shared-decision invalidation agreement + Conductor inspection wiring

Ten additive node IDs in two suites; no existing test moved. Two verifier
findings are closed with production behavior, not fixture assertions:

1. **Under-invalidation of relayed shared fields** — `_shared_signature`
   (packages/maistro-design/src/maistro_design/creative_graph.py) omitted
   `beneficiaries`, `goal_owner_agent_id` and `goal_delegation_ref`, while
   `shared_decision_digest` (creative_nodes.py) digests them into the
   message-decision identity every branch cites. Executed repro before the
   fix: all three changes reported `shared_context_changed=False` with zero
   invalidated branches while the digest moved. The signature now mirrors the
   digest's shared slice, so the invalidation answer and the decision
   identities are one authority.

   `test_creative_graph.py` (+6): parametrized over the three fields (plus
   delegation-moved/delegation-removed shapes) asserting every branch
   invalidates and the reason names the field
   (`test_relayed_shared_field_changes_invalidate_every_descendant`); the
   digest-side mirror holding the brief fixed
   (`test_shared_decision_identity_covers_the_relayed_agent_and_beneficiary_fields`);
   and a no-op `new_version` pinning that version minting alone invalidates
   nothing (`test_new_version_with_unchanged_decisions_invalidates_nothing`).

2. **AC-10 not reachable in Conductor** — `artifact_provenance` had zero
   consumers outside maistro-design, and hive-conductor's
   `services/dag_run_inspection.py` exposed no provenance/goal/brief/
   delegation/artifact fields. The inspection door now relays the canonical
   `goal_run_evidence` provenance block (`creative_provenance` on list
   summaries and detail) and, on detail only, per-artifact records
   (`artifacts`) reconstructed from the persisted DurableRunRecord via
   `artifact_provenance` — attached only after the same scoped overlay that
   already authorized the canonical Run, so no second authorization door.
   `services/engine.py` gained the `graph_run_store` bridge property
   (mirrors `run_reader`).

CI-repair bookkeeping in the same round: `quality/vulture-baseline.json` was
amended from a real scan (`check-vulture-baseline.py --update`, exact lane
command) to bank the 33 reviewed retained vulture identities this branch's
#774/#775 code introduced (pydantic model-validator methods, versioned-brief
and stage-output contract fields, planning/inspection dataclass fields — none
genuinely dead, so no code was removed) and to prune the 2 identities the
whole-tree scan no longer reports (`maistro_design/types.py::'family'` is
read by `systems/loader.py`; `maistro/workspaces/model.py::'_require_non_blank'`
is consumed in-tree). The trusted-base half of that gate still requires a
separately landed reviewed grant in `quality/ratchet-authorizations.json`
(two-merge rule: grants are read from the base revision, so this branch
cannot authorize its own debt).

   `test_dag_run_creative_inspection.py` (+4): the real reference Graph runs
   through the canonical durable executor and `visible_run_detail` must name,
   per artifact, the Goal revision, brief version, shared decision identities
   (one message-decision id cited by all three branches), owner agent,
   delegation ref, status and attempt counts; a non-creative run gains no
   creative block; an out-of-scope caller still gets the 404-shaped refusal;
   a missing durable spine degrades to the run-level block (`artifacts: []`)
   instead of failing the read.

## Round 2 addendum — salvaged signature extension + CI-gate evidence repairs

**Salvaged src work committed.** The prior run left uncommitted edits
(backed up as `incoming-775-salvage.patch` before continuation) extending the
shared-decision agreement to three more relayed fields: `success_interpretation`,
`source_references` and `supervision_constraints` — added to `_shared_signature`
(creative_graph.py) and to `_SHARED_CONTEXT_FIELDS`/`shared_context_from_brief`
(creative_nodes.py) so both authorities move together. Without them, changing
the brief's success interpretation, source artifacts or supervision notes left
siblings planned against a stale digest.

`test_creative_graph.py` (+3 params, +3 digest-loop entries, same two
agreement tests): the invalidation parametrization and the digest-identity
loop now cover the three salvaged fields, pinning that neither authority
covers a field the other ignores for them either.

**CI `test` gate evidence repairs** (all reproduced locally before fixing):

1. `quality/reachability-baseline.json`: `maistro.interop` and
   `maistro.interop.contract` became reachable after the develop merge
   (c1f1fa0e); `scripts/check-reachability.py` itself prescribes the ratchet
   shrink, so both entries were dropped (189 -> 187), and the 1:1 ledger
   `quality/reachability-dispositions.json` moved with it (empty
   `interop-contract` group pruned). Provenance gate accepts the shrink:
   `check-reachability-dispositions-provenance.py` exit 0
   ("189 dispositioned modules -> 187").
2. `docs/specs/SPEC-092826-a774-creative-brief-contract.md`: status
   `AC Defined` requires `owners` (lifecycle machine, ADR-097) and the
   registry linter requires `layer`. Added `owners: ['@BlakeMatthews-dev']`
   (the spec's author) and `layer: Foundation` (matches sibling
   SPEC-091726-7c2a brief-contract spec). `python -m maistro_registry.cli
   lint . --strict`: 414 files, 0 errors; `tools/lint_lifecycle.py`: all
   documents pass, baseline 0 accepted.

Two full-suite runs also showed `tests/test_check_merge_markers.py::
test_this_repository_is_clean` and hive-conductor's
`test_independent_process_writers_publish_one_username` failing only under
full-suite load and passing in isolation (subprocess/timing flakes near the
60s per-test timeout); both pass standalone and `scripts/check-merge-markers.py`
reports the tree clean. Not addressed further: no diff-reachable cause.

**Suite-inventory alignment (+2 design).** The develop merge (c1f1fa0e)
moved `docs/testing/inventory/baseline.json` under this branch's recorded
deltas: at the pre-round head the design suite already collected 430 against
an expected 428 (no test was added by the salvage commit c72b10cb — verified
by diff), and this round's +3 parametrized cases bring collected to 433. The
note's delta is therefore 6 + 3 + 2 = 11 so `check-suite-inventory.py`
reconciles to the tree exactly; no test was deleted or weakened to make the
count line up.
