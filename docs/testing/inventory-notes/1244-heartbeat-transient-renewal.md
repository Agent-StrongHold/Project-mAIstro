---
inventory-delta:
  packages/maistro-core/tests: +2
---
# One transient heartbeat-renewal failure no longer marks a live executor dead (#1244)

Two maistro-core node IDs, both in `tests/runs/test_execution_fencing.py`, next to
the lease-reclamation tests they correct rather than replace.

`test_one_transient_renewal_failure_does_not_mark_a_live_executor_dead` is the
regression for the audit finding: the executor's heartbeat used to return
permanently on *any* `renew_lease` exception, so a single store blip stopped
renewal while the executor kept running in the same process. The lease then
lapsed through nobody's death and a reclaim sweep would settle a live Attempt —
the double-execution window. The test fails against that behaviour exactly where
the harm lands: the mid-flight sweep reclaims the Attempt, and the executor's
terminalization then dies on `illegal transition: cancelled -> cancelled`, its
physical outcome destroyed and its work queued for redispatch. With the fix, the
blip costs one tick, renewal resumes, the sweep comes back empty, and the lease
expiry is provably pushed past the initial TTL.

`test_a_permanent_renewal_refusal_still_stops_the_heartbeat` pins the half the
fix must not regress: a refusal that can never turn into a renewal (terminalized
Attempt, expired lease, superseded token) still ends the heartbeat after one
attempt instead of retrying for the life of the executor.

ADR-082526-b36a carries a dated amendment correcting the one sentence that
claimed a failed renewal was "the same as death, which is safe"; the ADR's
decision — liveness proven by renewal, TTL/3 cadence, fenced renewal, lapse then
reclaim — is unchanged, and AC-7's permanent-death simulation still passes
because reclamation is driven by lease expiry, not by the heartbeat quitting.
