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

## ADR-070426-3a1f: A2UI declarative agent-driven UI protocol adoption

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Revalidate A2UI v0.10 against the current upstream/protocol shape before pinning, then design it as a declarative UI capability transported through the canonical API/session surface. Agent-generated UI actions must resolve through canonical principal authorization and Capability Invocation; A2UI must not become a side-channel for effects. Keep maistro-design code/artifact generation separate from live declarative UI.  
**Current state:** The safe-like-data catalog model is a strong fit for MAIstro's control posture and solves a different problem from static/code design outputs. The proposal predates current execution and identity convergence, so transport/action ownership needs updating before acceptance.  
**ADR:** [ADR-070426-3a1f: A2UI protocol adoption](../../../adr/ADR-070426-3a1f-a2ui-declarative-ui-protocol-adoption.md)

## ADR-082426-2192: maistro-server builds one Container

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Preserve one Container/one spine/one run-id namespace in maistro-server and finish eliminating any direct `run_task` or hand-wired execution door that bypasses Conduit/admission/security. As older Conductor-specific agent wrappers retire, route through current Graph/Run/Capability architecture rather than preserving their behavior for compatibility.  
**Current state:** This is a key server-boundary convergence decision: the OpenAI-compatible door must enter the same DI/security/execution system as every other request.  
**ADR:** [ADR-082426-2192](../../../adr/ADR-082426-2192-maistro-server-builds-a-container.md)

## ADR-082426-6201: In-agent delegation is not a NodeRun

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Preserve NodeRun's meaning as execution of a Graph Node. Runtime strategy delegation inside one Node stays attributable through delegation provenance; remote/independent delegated work that deserves lifecycle identity becomes a child Run. Continue deleting constructed-but-unread A2A surfaces.  
**Current state:** This prevents runtime reasoning choices from mutating the Graph's logical NodeRun shape while still making delegation visible.  
**ADR:** [ADR-082426-6201](../../../adr/ADR-082426-6201-in-agent-delegation-is-not-a-node-run.md)
