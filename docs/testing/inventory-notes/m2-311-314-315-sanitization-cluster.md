---
inventory-delta:
  packages/hive-conductor/backend/tests: +35
---
# m2-311-314-315 — the Conductor sanitization cluster

One lane, three issues, one boundary surface: untrusted content crossing into
Conductor's browser sinks, widget configuration, and chat/voice dispatch.

The +35 backend node IDs are two files:

- `tests/test_chat_voice_gates.py` (new, 28 IDs) proves the #315 boundary:
  prompt injection refused on `/v1/chat/complete`, `/v1/chat/stream`, and
  `/v1/voice/intent`; both chat routes share one `gate_untrusted` call
  (parity by construction); encoded variants refused; benign requests pass;
  hostile strings refused whatever role carries them; scanner outage,
  scanner timeout, malformed scanner output, and scan-budget overflow each
  fail closed with their own explicit status; model-authored tool arguments
  blocked before dispatch; indirect injection in tool results withheld
  before the next model turn; allowed tool calls recorded with
  gate_id/policy provenance; and the dispatch policy — destroy/mutate need
  an approval the model cannot mint, networked needs a principal, unknown
  tools are refused.
  The six later IDs close the arcs named by the diff-coverage gate: the
  streaming refusal answered as an ordinary `done` event with no model
  call, the non-streaming loop dispatching a clean tool call on the same
  boundary, a crashing tool reported as a tool result rather than an
  exception, a non-dict scanner verdict failing closed, the refusal copy
  distinguishing scanner unavailability, and a caller-presented approval
  authorizing (with audit) a destructive tool.
- `tests/test_dashboard_request_containment.py` (+7 IDs, 3 → 10) grows the
  #314 half: the per-type strict schema keeps declarative fields and drops
  unknown ones, scheme/traversal/percent-encoded payloads are rejected and
  *named* as violations, non-primitive shapes and over-deep nesting drop,
  the widget envelope (title/size/rows) is constrained, free-text fields
  keep formula characters but not traversal, and the `create_dashboard_widget`
  chat tool now rejects non-declarative configs instead of saving a shell.

`tests/test_m0_tool_containment.py` changed one test without moving the
count: its "ordinary chat never enters the tool loop" case used hostile text
the #315 gate now refuses upstream, so it was reworded to a gate-clean
message to keep proving containment on the ordinary path rather than passing
vacuously through the new refusal.

Not in this count, deliberately: the lane also adds
`packages/hive-conductor/tests/e2e/widget-capabilities.spec.ts` (5 Playwright
tests) and both e2e specs gained a local-run source-root override. The e2e
suite row counts pytest node IDs only; Playwright specs are browser proofs,
executed by the `hive-conductor-e2e-ui` compose job — and, with
`E2E_SRC_ROOT`/`E2E_NODE_PATHS` set, from a worktree.

#311 itself added nothing: the deck sanitizer and its browser proof landed
with #752 and were re-verified green here (4 deck e2e tests against real
Chromium) after the chat boundary change, since Deck Builder's chat surface
rides `/v1/chat/complete`.
