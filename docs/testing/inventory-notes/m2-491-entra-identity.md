---
inventory-delta:
  packages/maistro-core/tests: +15
  packages/hive-conductor/backend/tests: +6
---
# M2 #491 Entra identity specialization

Adds fifteen maistro-core pytest node IDs covering tenant-specific Microsoft
Entra provider metadata, rejection of multi-tenant aliases, cryptographically
downstream `tid`/`oid` normalization, cross-tenant collision resistance,
wrong-tenant failure, missing/invalid immutable claims, mutable email/UPN
independence, and stored-subject parsing.

Adds six Hive backend node IDs for the explicit human-login mode contract:
`local`, `entra`, and `hybrid`, with Entra-only password refusal and a distinct
operator-controlled break-glass exception seam.

The implementation extends the now-merged generic OAuth product wiring without
creating a second OAuth client, link store, session model, or authorization
authority.
