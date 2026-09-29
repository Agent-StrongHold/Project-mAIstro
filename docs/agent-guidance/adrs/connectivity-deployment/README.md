# Connectivity & Deployment ADRs

Progressive-disclosure index for ADRs governing networking, ingress, transport, deployment reachability, and related runtime exposure.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-029: Networking & Identity Substrate — Pluggable transport layer

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the substrate abstraction with current canonical authentication before implementation. Separate transport/reachability/TLS concerns from authentication authority: substrate-supplied identity claims may become principals only through an explicitly authenticated trusted-ingress binding that strips/sets claims; arbitrary request headers must never confer identity or privilege. Then decide which substrate implementations remain required and create a current spec/tests.  
**Current state:** No current Substrate implementation or Tailscale/NetBird/etc. identity-header adapter was located. The transport abstraction remains potentially useful, but the ADR's direct header-to-admin/user mapping predates the current canonical-principal/authentication work and must not be treated as current authentication behavior. Localhost/network exposure and identity verification are separate security concerns in the current architecture.  
**ADR:** [ADR-029: Networking & Identity Substrate — Pluggable transport layer](../../../adr/ADR-029-networking-substrate.md)
