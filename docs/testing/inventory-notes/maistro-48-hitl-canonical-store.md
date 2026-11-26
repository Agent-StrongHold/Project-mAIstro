---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +8
---
# maistro-48-hitl-canonical-store

The HITL repair adds wiring regression coverage in `test_dag_agents.py` and
`test_hitl_timeout_cancel.py` proving that a Conductor without a canonical
spine cannot obtain, expose, or start standalone HITL work. Existing route tests bind their
document-shaped fixture explicitly to the new canonical-store seam, so they no
longer assert that the production route uses `InMemoryDurableRunStore`.

The repair follow-up adds the missing canonical-store coverage the CI
diff-coverage gate named: the answered-HITL reconciler now has a test for
every repair outcome — requeueing a node still paused behind its accepted
answer (then resuming to a continued Attempt history), refusing answer
evidence it cannot trust (non-mapping answers, non-string, unparseable, and
zone-less instants), refusing when the record cannot be assembled mid-repair,
and refusing to reopen already-settled nodes. A final test pins the resume
pre-flight repair's duck-typed fallback: a canonical store predating the
targeted `reconcile_run` affordance is repaired through the bounded
`reconcile_persistence(limit=1)` sweep.
