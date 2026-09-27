---
inventory-delta:
  packages/maistro-core/tests: +15
---
# claude-ws-286-governed-image-generation-capability-pro-d0e2

`packages/maistro-core/tests` grows by 15 node IDs, all in the new
`tests/capabilities/test_image_generation_egress.py` (#286): the governed
`image.generate` egress run through a real `create_container` effect context
with only the httpx transport faked. Eight single tests cover the authorized
call (one correlated Invocation, decoded bytes, Binding-scoped key), replay
without a second POST, request-selected model, unselected model, credential
scope, disabled/foreign-capability Bindings, policy denial and the physical
seam's type guards; one test is parametrized seven ways over refusal responses
(5xx, empty `data[]`, no `b64_json`, non-JSON, non-object entry, bad base64,
unreachable gateway), each of which must leave a FAILED Invocation. No test
was removed or moved.
