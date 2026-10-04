---
inventory-delta:
  packages/maistro-core/tests: +33
  tests/: +12
---
# Foreign harnesses as governed graph nodes (#1613, M1-D)

OpenClaw and Pi arrive as first-class governed harness nodes: two new
`harness_runner` capability providers, a bridge that dispatches a session-protocol
provider through the shipped `agent.spawn_harness` governed Invocation seam, a CI
gate that rejects product callers doing OpenClaw/Pi transport outside the Provider
boundary, and the wrap-don't-clone architecture note.

The twenty-nine new maistro-core node IDs cover each acceptance seam directly:

- `tests/capabilities/test_foreign_harness_providers.py` (18): the OpenClaw and
  Pi adapters at the real provider seam with a fake far side — one outbound
  gateway task (`openclaw agent --message`), one print-mode coding turn
  (`pi -p`), flag/quoting structure, exclusion of system messages so harness
  prompts cannot leak governed context, OpenAI-shaped envelopes, binary
  healthchecks, and microVM wiring that points each harness at the caller's
  workspace with operator-wired (never request-wired) credentials.

- `tests/graph/nodes/test_foreign_harness_invocation.py` (15): the governed
  path. The `HarnessRunnerDispatchAdapter` bridge performs exactly one bounded
  turn per dispatch — start_session, send, stop in a `finally` — so a failed
  turn still stops the session (no orphan claw session survives as canonical
  success), `poll` replays the memoized completed turn without re-dispatch,
  and the adapter satisfies the full `HarnessAdapter` protocol (dispatch,
  poll, cancel). Both OpenClaw and Pi dispatch through Binding -> governed Invocation, and the
  persisted Invocation rows carry the harness id, the session/workspace hint
  (adapter dispatch detail), and the result payload. A durable walk runs one
  Graph with one native node (`test.m1d_native_upper`) and one foreign-harness
  node: both NodeRuns and their Attempts share one canonical parent Run, the
  foreign node's pause metadata carries the invocation id a harness waker
  (#1192) will need, and the Invocation is stored under that same Run identity.
  The resume-evidence overlay is pinned at its degenerate halves: a poll that
  is still running, reports failure, or raises leaves the transported answer
  untouched, and a successful poll extends (never discards) the answer's
  metadata.

The twelve root-suite node IDs (`tests/test_check_foreign_harness_egress.py`)
cover the new gate both ways: OpenClaw-over-HTTPX, Pi-over-subprocess, and
direct `urlopen` are refused in product trees; the provider boundary, the
ADR-101 §2 peer transport (`orchestrator/hierarchy.py`), tests, and the gate
itself are exempt; marker-without-transport and transport-without-marker stay
clean; `dict.get`/`asyncio.run` false-positive guards hold; and the shipped
checkout scans clean.

Deliberately not covered here: waking `awaiting_harness` pauses end-to-end —
that waker is the ledgered #1192 gap, and the node-level resume contract is
already covered by `test_agent_spawn_harness.py`.
