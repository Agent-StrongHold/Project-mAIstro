---
inventory-delta:
  packages/maistro-core/tests: +5
---
# auto-1137-ci-coverage-repair — diff-coverage gate repair for #1137

The merge-queue run at 3364e1f failed the Coverage gate: `check-diff-coverage`
measured changed lines in `maistro/a2a/inbound.py` at 66.7% and
`maistro/graph/nodes/agent_delegate_remote.py` at 89.6%, both below the
per-file 90% floor. Five cases close the measured gaps; no production code
changed.

`maistro/a2a/inbound.py` (3 cases): the canonical representation's rich-value
encoder is exercised with an Enum, a datetime, a date and a self-projecting
`model_dump` value (deterministic sorted-key form asserted); a payload value
with no JSON form fails closed with `warden_unavailable` before the scanner is
reached (the scanner observes nothing); a scanner that raises fails closed the
same way.

`maistro/graph/nodes/agent_delegate_remote.py` (2 cases): a resumed answer that
is not a mapping is refused as an invalid representation — scanned in its exact
canonical form, audited as denied, child Run untouched, no peer text in the
node output; and an audit-backend outage during a denied scan still rejects
without raising, recorded as a warning that carries no peer content.
