---
inventory-delta:
  packages/maistro-server/tests: +4
---
# claude-ws-223-expose-each-noderun-s-attempts-including-c676

Four maistro-server node IDs arrive with exposing each NodeRun's Attempts
on `GET /v1/runs/{run_id}/node-runs` (#223). One chat test reads the completed
turn's Attempt back, including the dispatched agent. One chat test and one
task test check that a failed Attempt reports `failed` without leaking its
error or result text. One task test checks that only a chat Attempt names
an agent, so a graph node's own output cannot pose as one. The existing task and cross-principal tests also gained
assertions but no new node IDs. Nothing was removed.
