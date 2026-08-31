---
inventory-delta:
  packages/maistro-core/tests: +20
---
# fix-request-id-validation-d7fa

Request-ID middleware hardening expands the prior single valid-header example
into five accepted boundary forms (net +4), then adds sixteen collected cases
for oversized, whitespace, non-ASCII, punctuation, empty, control-byte,
delimiter, duplicate-header, and punctuation-only rejection. The resulting
`packages/maistro-core/tests` inventory delta is +20.
