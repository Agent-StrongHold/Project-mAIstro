---
inventory-delta:
  packages/maistro-core/tests: +15
---
# M2 #491 Entra identity specialization

Adds fifteen pytest node IDs covering tenant-specific Microsoft Entra provider
metadata, rejection of multi-tenant aliases, cryptographically downstream
`tid`/`oid` normalization, cross-tenant collision resistance, wrong-tenant
failure, missing/invalid immutable claims, mutable email/UPN independence, and
stored-subject parsing.

This slice is intentionally stacked on the active generic OAuth product-wiring
PR.  It adds Microsoft-specific identity semantics without creating a second
OAuth client, link store, session model, or authorization authority.
