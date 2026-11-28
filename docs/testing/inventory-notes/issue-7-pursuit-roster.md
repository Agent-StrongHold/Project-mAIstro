---
inventory-delta:
  packages/maistro-core/tests: +2
---

# Goal pursuit uses the loaded A2A roster

`tests/agents/test_factory.py` loads an agent through the filesystem roster
and requests a real in-process delegation receipt as the Goal pursuit sender.
Before the repair even the loaded target was refused with `no delegation
capabilities`. The two tests cover admission to a loaded target, refusal of
an absent target, and refusal of a manifest that occupies the reserved sender
name. The existing Goal admission test pins that sender on the queued Graph.
These checks do not establish idempotent physical Run creation after failover.
