---
inventory-delta:
  packages/maistro-design/tests: +6
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
