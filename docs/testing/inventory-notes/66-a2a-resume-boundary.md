---
inventory-delta:
  packages/maistro-core/tests: +2
---

# #66 A2A resume-boundary scans

Resumed `agent.delegate_remote` answers are remote peer output, so they cross
the canonical Warden boundary before they re-enter trusted Run/Agent context
(#66 / #1137). The trunk's canonical implementation scans the whole
peer-controlled answer — dispatch inputs and resumed answers alike — in its
exact canonical JSON form (`maistro.a2a.inbound.scan_inbound`), with
attacker-controlled mapping keys included in the scanned text, audit
recording, and a refusal that settles the child Run and relays no
peer-controlled result text. This lane's original field-by-field scan was
re-applied onto a develop trunk that had already landed that superset
(#2168), so the merge kept the trunk implementation.

What this lane adds on top are two properties the trunk did not yet pin:

- `test_in_process_resume_with_obfuscated_injection_is_refused`: a zero-width
  space inside "ignore" is folded to the plain pattern by the detector, so
  obfuscation does not evade the A2A boundary (#1158 normalization applies
  here too).
- `TestARefusedAnswerStillSettlesTheChild`:
  `test_a_warden_refused_answer_terminalizes_the_child` — a Warden-refused
  answer submitted through the durable HITL answer path still terminalizes
  the server-owned child Run (cancelled, refusal as evidence), and the
  parent's node result carries the refusal without the payload.
