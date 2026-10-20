---
inventory-delta:
  packages/maistro-core/tests: +25
---
# claude-ws-286-governed-image-generation-capability-pro-d0e2

`packages/maistro-core/tests` grows by 25 node IDs, all in the new
`tests/capabilities/test_image_generation_egress.py` (#286): the governed
`image.generate` egress run through a real `create_container` effect context
with only the httpx transport faked.

Single tests cover:
- the authorized call: one correlated Invocation with image usage, decoded
  bytes and a Binding-scoped key;
- replay without a second POST, and a request-selected model;
- refusals before any HTTP: an unselected model, credential scope,
  disabled/foreign-capability Bindings, unregistered or tampered Bindings and
  policy denial;
- the physical seam's type guards;
- the image blob store: the Invocation row records references rather than
  image bytes, replay refuses rather than regenerates when a blob is gone or
  no longer matches its recorded digest, a store that cannot keep the image
  fails retryably, and the in-memory store is content-addressed and satisfies
  the port.

One test is parametrized eight ways over refusal responses (5xx, empty
`data[]`, no `b64_json`, non-JSON, non-object entry, bad base64, non-image
bytes, unreachable gateway), each of which must leave a FAILED Invocation.
Another is parametrized three ways over accepted JPEG/GIF/WebP payloads. No
test was removed or moved.
