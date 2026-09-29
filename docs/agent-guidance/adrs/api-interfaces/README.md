# API & Interface ADRs

Progressive-disclosure index for ADRs governing HTTP/API surfaces, client parity, versioning, and external interface contracts.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-076: HTTP API Versioning via content negotiation

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **Create a successor ADR for the pre-1.0 canonical API surface, then supersede ADR-076.** Preserve the valuable rule that web/TUI/other clients use one governed API with no private side channels. Explicitly reject pre-1.0 version-preservation, sunset windows, compatibility branches, and content-negotiated old behavior: breaking changes should replace the current beta API directly because deployments are rebuilt from scratch. Define post-1.0 compatibility/versioning policy only when 1.0 is approached.  
**Current state:** No general ADR-076 content-negotiation implementation exists; the repository uses path-prefixed routes. More importantly, the ADR's central compatibility objective now conflicts with the explicit pre-1.0 development standard: backward compatibility has no positive value and can impede architectural convergence. The canonical-surface principle remains useful and should survive in the successor.  
**ADR:** [ADR-076: HTTP API Versioning via content negotiation](../../../adr/ADR-076-http-api-versioning.md)
