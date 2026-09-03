---
inventory-delta:
  packages/maistro-core/tests: +16
  packages/hive-conductor/backend/tests: +27
---
# M2 #491 Entra identity specialization

Adds sixteen maistro-core pytest node IDs covering tenant-specific Microsoft
Entra provider metadata, rejection of multi-tenant aliases, refusal of blank
client IDs and scopes without `openid`, cryptographically
downstream `tid`/`oid` normalization, cross-tenant collision resistance,
wrong-tenant failure, missing/invalid immutable claims, and mutable email/UPN
independence.

Adds twenty-seven Hive backend node IDs. Six cover the explicit human-login
mode contract: `local`, `entra`, and `hybrid`, with Entra-only password
refusal and a distinct operator-controlled break-glass exception seam.
Twenty-one drive the specialization through the real product wiring so it is
reachable rather than built-but-never-wired: Entra provider settings
(tenant-only configuration, multi-tenant alias refusal, explicit-endpoint
contract), tenant-specific v2 endpoint construction, an end-to-end Entra
login whose durable link is the immutable `tid:oid` pair rather than the
pairwise subject, wrong-tenant refusal, hybrid deployments keeping generic
providers on the generic verifier, and the login route consulting the
deployment mode policy (Entra-only denial, local/hybrid continuation,
request-uninfluenceable denial).

The implementation extends the now-merged generic OAuth product wiring without
creating a second OAuth client, link store, session model, or authorization
authority.
