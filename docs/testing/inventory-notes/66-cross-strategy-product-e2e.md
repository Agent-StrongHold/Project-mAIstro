---
inventory-delta:
  packages/maistro-core/tests: +10
  packages/hive-conductor/backend/tests: +2
---

# #66 Cross-strategy and product re-entry equivalence E2E

The #66 acceptance set has two criteria the earlier lane work implemented but
did not yet hold with tests at this head: "product E2E proves equivalent
enforcement across strategies and chat/harness/agent-scan/event/A2A re-entry
paths", and the strategy-divergence clause of #1202 ("Direct/ReAct/Artificer/
PlanExecute/BuildersLearning cannot choose different security pipelines"). The
existing `test_trust_pipeline_equivalence.py` pinned tool-result governance for
three of the five shipped strategies; nothing pinned the two boundaries every
strategy reaches (user turn, final assistant answer) across all five, and the
product E2E (`test_e2e_authenticated_real_model_graph.py`) stopped at the chat
surface.

Core: ten new parametrized cases sweep every shipped strategy name in the
factory registry (`direct`, `react`, `plan_execute`, `artificer`,
`builders_learning`) through `Agent.handle` with a real Warden, a real
Sentinel and a FauxProvider. The hostile-turn case pins that the identical
injection is a pre-provider refusal for every strategy (zero provider calls,
input gate only); the PII case pins that the identical model answer reaches
the caller with the same redaction for every strategy, produced by exactly one
input scan and one output scan — a strategy-local second pipeline would show
up as extra boundaries, a bypassing one as missing ones. The recording warden
delegates every scan to the shipped detector, so the shape claim is about a
real pipeline, not a stub's call count.

Conductor: two new legs extend the authenticated real-model E2E. The
cross-path leg drives one hostile payload over product HTTP through chat
(`content_filter` refusal), the harness send route (through the manager the
route itself lazily builds, refused with a warden 400) and the forge
agent-definition door (`scan_config` walk, 400 before anything is stored),
asserting each consultation went to the same composition-root detector, that
no second `Warden` was constructed (a spy fails immediately instead of
downgrading silently), and that the model gateway saw none of it. The A2A leg
drives `scan_inbound` — the boundary a remote-delegation resume result crosses
(#1137) — with the zero-width-space split form, and pins the canonical
representation: the detector must judge the character the peer sent, and the
payload is chosen so the split is the whole attack (under the ASCII
transcription the pre-#1158 canonicalizer produced, this exact text scans
clean, no secondary pattern rescues it), so the leg fails if that
canonicalization regresses rather than merely if scanning stops.

Not claimed here: harness-path enforcement under a *streaming* turn, and the
RSI (#1138) / one-invariant-pipeline closure (#1202) criteria — those are
upstream child issues, still open at the time of this note.
