inventory-delta:
  packages/maistro-core/tests: +17
---

# Self-repair approval wait: restart/replica convergence and reconstructible resume (#2405)

Seventeen maistro-core node IDs in a new
`packages/maistro-core/tests/capabilities/test_self_repair_incident_dedup.py`,
pinning the two coordination contracts the #2405 audits proved broken:

- **One incident, one Run.** Stable incident identity (workspace/resource/
  action/request digest, no `id(proposal)`), an atomic same-incident claim
  through the existing occurrence-claim unique index (`DuplicateOccurrence`
  losers reconcile to the winner), crash-window re-entry of the claimed Run,
  refusal of a claim held for a different effect, distinct incidents never
  aliasing, terminal settlement chaining the next episode, and hydration
  gating a fresh provider/replica (with hydration failure failing the whole
  cycle closed).
- **Approved work resumes.** The registered `infra.approval_gated_action`
  kind composes from durable facts plus Container-owned authorities: an
  answered pause resumes through `resume_durable_graph` with exactly one
  physical effect, a second tick is inert, missing authorities fail
  composition closed, and a revoked Binding fails the resume closed with zero
  dispatch.

All seventeen run on the in-memory spine (canonical `InMemoryRunStore` +
`CanonicalDurableRunStore` wrapper); none is skipped. The interleaving
coverage is asyncio-concurrency and simulated crash windows, not real
multi-process PostgreSQL kills — the audit's real-kill/replay proofs (slice 4)
remain unexecuted here and are not claimed. One existing file gained no new
node IDs but a new authority mapping row
(`test_container_node_composition.py::capability_registry -> capabilities`),
which holds the composition-root contract for the new authority.
