# Historical inventory notes (pre-split archive)

Every note recorded in `SUITE-INVENTORY.md` before the per-change split
(#208) is preserved here verbatim, oldest-first as it accumulated. It is a
single file because the original was a single block: the individual changes
were never separated at the time, and inventing boundaries now would be a
guess. New notes go in their own file — see `README.md` in this directory.

Nothing here should be edited. It is a record of what was written, not a
document to keep current.

---


Refreshed after the runtime cleanup queue (#355, #359, #361), the promotion
CI reconciliation, the Workspace/Persona convergence slice, and Stream 5 parity
characterization. The convergence work adds 44 maistro-core node IDs covering
ExecutionRuntime mechanics, Project to Workspace compatibility,
WorkspaceMembership role semantics, the live Persona model, and
one-Persona-per-Workspace persistence. Stream 5 adds four maistro-core node IDs.
Graph routing parity in #402 adds 10 maistro-core node IDs.
Graph execution-state frontier coverage in #403 adds nine maistro-core node IDs.
Durable graph canonical-persistence convergence in #416 replaces legacy
DurableRun/DurableNode lifecycle tests with canonical Run/NodeRun coverage,
for a net reduction of six maistro-core node IDs while retaining the
durability, routing, HITL, restart, mutation, and persistence invariants.
Real durable Graph frontier execution adds six maistro-core node IDs covering
concurrent fan-out, deterministic NodeRun ordering, source-correlated routing,
and fan-in input merging.
Durable Attempt/Runtime-boundary convergence adds nine maistro-core node IDs
covering Attempt ownership, shared durable persistence, deferred domain
reconciliation, real frontier execution through Attempt execution IDs,
cancellation terminalization across Attempt, NodeRun, and Run, and recovery by
appending a second Attempt under the same logical NodeRun.
Accepted AttemptResult/NodeRun outcome separation adds nine maistro-core node
IDs. Durable execution-lease fencing adds five more maistro-core node IDs.
Authoritative TraversalCommit/TraversalCheckpoint contracts add eleven
maistro-core node IDs.
PR #447 adds six maistro-core node IDs covering checkpoint-bridged traversal
history, reuse of frozen execution state across transitions, and rejection of
execution continuation after an accepted logical completion.
Stream 1 adds 99 maistro-core node IDs for the canonical Project,
Run/NodeRun/Attempt, runtime, persistence, and execution-service contracts.
Stream 6 adds five provider-parity node IDs.
Stream 3 authorization/resource-scope coverage adds 19 maistro-core node IDs.
Stream 7 product-adapter parity adds four maistro-core and two maistro-canvas
node IDs.
Stream 2 event, checkpoint, and outbox coverage adds 51 maistro-core node IDs.
The repo-task wrapper compatibility regression adds one maistro-evolve node ID.
Reachability production-root coverage adds four root-suite node IDs.
Mutation scheduler/history coverage adds ten root-suite node IDs.
Mutation continuation and repository-health aggregation add fifteen root-suite
node IDs, including checkpoint cache stability, complete-row-only baseline
aggregation, and single-tool-fingerprint sweep validation.
Mutation ratchet coverage adds seven root-suite node IDs for the global floor,
source-specific non-regression, monotonic baseline improvement, survivor
identity reporting, runtime regression confidence, and incomplete telemetry
rejection. Two more come from splitting the superseded unbaselined-source case
into the floor-fails, floor-passes, and candidate-merge assertions it had been
conflating.
Workspace creation was deliberately moved out of the scope-gated parametrized
Hive cases and into the ordinary product-surface check, so Hive loses one
collected node ID while retaining the intended assertion. Durable approval
coverage now includes stateful policy charging of human-approved effects before
provider dispatch. The Graph capability-effect adapter adds one maistro-core
node ID, covering the pause-then-resume path: the first Attempt pauses with
durable approval provenance and the second executes the approved effect without
a duplicate approval or Invocation. Other suite counts are unchanged.

Fifteen maistro-core node IDs arrive with two security fixes on this branch.
Sentinel argument limits (#68) contribute the larger share: a new
`test_argument_limits.py` covering per-argument and total-payload caps.
Warden's L3 judge (#71) contributes the rest, covering each way an inconclusive
classifier result reaches the caller — provider error, timeout, empty body,
malformed body, a partial answer that names no verdict, and the judge being
unreachable altogether — since the point of the fix is that none of those may
read as `safe`.

Ten more maistro-core node IDs arrive with PII-evasion normalization (#70): five
for the acceptance and same-length homoglyph-offset invariants, then five from
adversarial review covering Base64 SSNs, percent-encoded connection strings,
form-encoded phones, encoded-span absorption/idempotence, and partial-overlap
refusal.

