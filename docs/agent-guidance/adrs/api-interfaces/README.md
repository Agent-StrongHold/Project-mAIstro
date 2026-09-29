# API & Interface ADRs

Progressive-disclosure index for ADRs governing HTTP/API surfaces, client parity, versioning, and external interface contracts.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-076: HTTP API Versioning via content negotiation

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **Create a successor ADR for the pre-1.0 canonical API surface, then supersede ADR-076.** Preserve the valuable rule that web/TUI/other clients use one governed API with no private side channels. Explicitly reject pre-1.0 version-preservation, sunset windows, compatibility branches, and content-negotiated old behavior: breaking changes should replace the current beta API directly because deployments are rebuilt from scratch. Define post-1.0 compatibility/versioning policy only when 1.0 is approached.  
**Current state:** No general ADR-076 content-negotiation implementation exists; the repository uses path-prefixed routes. More importantly, the ADR's central compatibility objective now conflicts with the explicit pre-1.0 development standard: backward compatibility has no positive value and can impede architectural convergence. The canonical-surface principle remains useful and should survive in the successor.  
**ADR:** [ADR-076: HTTP API Versioning via content negotiation](../../../adr/ADR-076-http-api-versioning.md)

## ADR-096: Hive Conductor / maistro-server boundary

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Complete the M1 cutover by physically retiring Hive-owned production execution, TaskRunner/Graph executor, sandbox, and security-effect paths. Clarify the authority statement: canonical execution state/lifecycle is Run/NodeRun/Attempt in maistro-core; maistro-server is the governed API/control-plane composition that admits and exposes it; Hive is a UI/BFF client. Under the pre-1.0 standard, remove any demo/stub execution path that can become a second behavioral authority rather than preserving it for compatibility.  
**Current state:** This ADR states the correct convergence direction and directly addresses a major source of duplicate execution authority. The remaining work is not conceptual: Hive legacy execution paths have been active retirement targets throughout M1, and the boundary is only complete when production reachability and security effects flow exclusively through the canonical core/server path.  
**ADR:** [ADR-096: Hive Conductor / maistro-server boundary](../../../adr/ADR-096-hive-server-boundary.md)
