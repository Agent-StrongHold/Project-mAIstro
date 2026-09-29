# Connectivity & Deployment ADRs

Progressive-disclosure index for ADRs governing networking, ingress, transport, deployment reachability, and related runtime exposure.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-029: Networking & Identity Substrate — Pluggable transport layer

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the substrate abstraction with current canonical authentication before implementation. Separate transport/reachability/TLS concerns from authentication authority: substrate-supplied identity claims may become principals only through an explicitly authenticated trusted-ingress binding that strips/sets claims; arbitrary request headers must never confer identity or privilege. Then decide which substrate implementations remain required and create a current spec/tests.  
**Current state:** No current Substrate implementation or Tailscale/NetBird/etc. identity-header adapter was located. The transport abstraction remains potentially useful, but the ADR's direct header-to-admin/user mapping predates the current canonical-principal/authentication work and must not be treated as current authentication behavior. Localhost/network exposure and identity verification are separate security concerns in the current architecture.  
**ADR:** [ADR-029: Networking & Identity Substrate — Pluggable transport layer](../../../adr/ADR-029-networking-substrate.md)

## ADR-047: Outbound Delivery Gateway — Multi-channel notifier

**Status:** Deprecated  
**Last updated:** 2026-09-28  
**Next steps:** No implementation work against ADR-047. Remove its unreachable implementation during island/convergence cleanup unless a new accepted ADR reintroduces outbound delivery with a current canonical execution path.  
**Current state:** ADR-047 was explicitly corrected from an implementation claim to Deprecated after reachability analysis proved the shipped delivery gateway had no process-entry-point path. Nothing supersedes the withdrawn contract. This is a canonical example of why code/test existence is insufficient evidence without production reachability.  
**ADR:** [ADR-047: Outbound Delivery Gateway — Multi-channel notifier](../../../adr/ADR-047-delivery-gateway.md)

## ADR-081: Deployment Topology, Backup, and Disaster Recovery

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite before acceptance to separate **ephemeral deployment rebuildability** from **persistent user-data durability**. Pre-1.0 application deployments may be destroyed/rebuilt with no backward-compatibility guarantee; backups/restores should protect current persistent data/config/secrets without promising old-version schema compatibility. Replace ADR-071 backpressure and Task-era drain assumptions with canonical Run admission/drain/recovery semantics. Reassess whether cross-platform import/export is a current product requirement or a later stable-schema feature.  
**Current state:** The local-backup floor and portable-data goals remain useful, but the proposal mixes them with deployment rolling-update/compatibility assumptions and stale orchestration dependencies. Scratch deployment before 1.0 does not eliminate the need to protect beta user data; it does eliminate the need to preserve old application/API/schema behavior merely so an old deployment keeps running.  
**ADR:** [ADR-081: Deployment Topology, Backup, and Disaster Recovery](../../../adr/ADR-081-deployment-backup-dr.md)

## ADR-102: Sibling packages use maistro-core's central outbound HTTP guard

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile lifecycle metadata and promote to `Implemented` if the bound tests remain green. The ADR already carries `implemented: 2026-09-14`, all four ACs are checked, concrete tests are listed, and the security-inventory census asserts no sibling package bypasses the central outbound seam; the missing piece is a valid ADR-097 Implemented history/status transition.  
**Current state:** This is a strong example of current architecture: outbound HTTP/SSRF policy is centralized in maistro-core, sibling packages depend on that seam rather than vendoring controls, configured origins are exact allow-lists, and the decision explicitly introduces no execution authority. Evidence is direct and repository-wide.  
**ADR:** [ADR-102: Sibling packages use maistro-core's central outbound HTTP guard](../../../adr/ADR-102-central-ssrf-guard-for-sibling-packages.md)
