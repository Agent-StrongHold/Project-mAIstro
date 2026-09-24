---
inventory-delta:
  packages/maistro-core/tests: +12
---
# auto-147-6ac7

Adds the delegation child-run regressions: a cross-instance resume proves
the child completes through a yielded and completed canonical Attempt rather
than direct Run terminalization, while an inline subgraph remains request
context on an opaque child node because the A2A transport sends only the text
task. The broader issue coverage also records scope refusal, child attribution
and lifecycle edge cases; the separate delegation receipt, direct-admission,
and factory-wiring notes explain those focused additions.

The +1 on top of the earlier +11 is the merge repair recorded in
`auto-147-merge-pause-wakers.md`: the #1192 waker map gains
`awaiting_remote_delegation -> _HUMAN_WAKERS`, its UNWOKEN ledger entry leaves
(gap closed by the durable answer seam this branch built), and one positive
pin proves `answer_record` delivers a paused delegation's answer with the
child Run id stamped from the node's own pause.
