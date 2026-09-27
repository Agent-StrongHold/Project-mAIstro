---
inventory-delta:
  packages/maistro-core/tests: +20
---
# claude-ws-286-governed-image-generation-capability-pro-d0e2

`packages/maistro-core/tests` grows by 20 node IDs, all in the new
`tests/capabilities/test_image_generation_egress.py` (#286): the governed
`image.generate` egress run through a real `create_container` effect context
with only the httpx transport faked. Nine single tests cover the authorized
call (one correlated Invocation with image usage, decoded bytes, Binding-scoped
key), replay without a second POST, request-selected model, unselected model,
credential scope, disabled/foreign-capability Bindings, unregistered or
tampered Bindings, policy denial and the physical seam's type guards. One test
is parametrized eight ways over refusal responses (5xx, empty `data[]`, no
`b64_json`, non-JSON, non-object entry, bad base64, non-image bytes,
unreachable gateway), each of which must leave a FAILED Invocation, and one
three ways over accepted JPEG/GIF/WebP payloads. No test was removed or moved.
