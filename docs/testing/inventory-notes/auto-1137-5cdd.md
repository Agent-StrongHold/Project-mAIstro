---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-1137-5cdd — develop merge resolution for #1137

One collected case over the branch's recorded +9: merging origin/develop's
M9-D2 governed-delegation rewrite onto the Warden ingress work added
`test_denied_resume_is_audited_and_leaves_no_result_text`, which pins the
merge's new settlement behavior — a resumed answer refused by the Warden scan
is settled through develop's canonical `AttemptLifecycleReconciler` path
(child Run terminal, no peer result text copied into the node output) and the
denial is attributed to the delegating lineage in the security audit trail
(task receipt named, scanned content absent from the record).

No tests were removed or renamed; the branch's nine prior cases carry over
adapted to the governed API (delegation contexts on the guest-peer transport
tests, the composition authority sweep extended with the two new
Container-owned authorities `warden`/`audit_log`).
