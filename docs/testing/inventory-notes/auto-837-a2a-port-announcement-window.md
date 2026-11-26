---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-837 — a2a peer port-announcement window

One new case in `packages/maistro-core/tests/a2a/test_guest_peers.py`
(`test_peer_port_announcement_tolerates_the_empty_creation_window`),
plus the matching hardening of the `_CrossProcessPeer._base_url`
helper it pins. Nothing removed or moved.

The coverage (no services) gate failed on
`test_cross_process_peer_injection_refused_by_canonical_warden` with
`ValueError: invalid literal for int() with base 10: ''` at
`test_guest_peers.py:113`: the peer child's `open(path, "w")` creates
the port file before the port is written, and the parent's
`exists()`-then-`read_text()` race parsed that window as a port under
CI load. The helper now treats only an all-digit body as announced, and
the new case makes the window deterministic by pre-creating the empty
file — the old reader fails on its first poll, the current one waits
for the real write.
