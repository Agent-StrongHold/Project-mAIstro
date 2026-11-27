---
inventory-delta:
  packages/maistro-server/tests: +3
---
# #66 The Conductor's blocked-final-answer arc must be exercised

CI's diff-coverage gate (quality.yml coverage-gate, run 45881362934, job
140142182585) failed on
`packages/maistro-server/src/maistro_server/conductor_agent.py`:
"50.0% of 2 changed branch arcs (need 80%); partial at 143". Line 143 is
`if outcome.blocked:` at the Conductor's final-answer Sentinel boundary —
the blocked arc was never taken, so a regression that dropped the blocked
answer on the floor (or leaked the raw `final_answer` anyway) had no
server-side test to fail.

Three tests in
`packages/maistro-server/tests/api/test_conductor_agent.py`:

- a blocking Sentinel yields `AgentResponse.blocked_response` carrying the
  gate's `block_reason`, with the raw `final_answer` absent from the content
  the caller sees;
- a block with an empty `block_reason` still names the boundary
  ("Final response blocked by Warden") instead of an unexplained refusal;
- a caller-supplied principal reaches `Sentinel.process_output` as itself —
  the `auth is None -> ANONYMOUS_AUTH` substitution is a fallback, not a
  replacement of a real principal (the #66 acceptance line "auth context
  cannot silently be absent on protected paths", in its inverse form).

Production code is untouched; this is coverage repair only.
