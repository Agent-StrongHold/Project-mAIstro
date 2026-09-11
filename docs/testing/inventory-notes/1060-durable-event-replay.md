---
inventory-delta:
  packages/maistro-core/tests: +5
---

# Issue #1060 durable event replay

The durable-event tests now distinguish local dispatch leasing from remote
commit idempotency. They cover unsafe handlers being held, worker death before
dispatch, delivery failure during the call, remote commit before local SUCCESS
persistence, replay after an expired lease, and stable HTTP `Idempotency-Key`
headers. The post-commit crash test models a handler-owned effect store keyed by
`maistro-event:{trigger_id}:{event_id}` and proves redelivery creates one logical
effect while the local invocation eventually reaches SUCCESS.
