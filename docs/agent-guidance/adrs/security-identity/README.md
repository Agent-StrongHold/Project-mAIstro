# Security & Identity ADRs

Progressive-disclosure index for ADRs governing authentication, authorization, identity, trust roots, credentials, security boundaries, and related governance controls.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-021: Conductor Seed — BIP39/BIP32 HD root of trust

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether ConductorSeed remains a desired opt-in capability under the current identity/authentication architecture. If yes, create/update an implementing spec that explicitly keeps baseline authentication, authorization, vault access, and agent identity independent of the seed, then implement and security-test derivation, recovery, signing, storage, and zeroization. If no, create or identify the successor decision and transition ADR-021 to `Superseded`.  
**Current state:** No ConductorSeed implementation was located in the current runtime. The ADR's 2026-06 amendment already changed the original root-of-everything premise: seed/DID/wallet functionality is optional and baseline credentials remain standalone. Current agents must therefore not treat BIP39/BIP32 seed material as a prerequisite or authority for authentication, authorization, vault operation, or agent identity.  
**ADR:** [ADR-021: Conductor Seed — BIP39/BIP32 HD root of trust](../../../adr/ADR-021-conductor-seed.md)

## ADR-022: Hardware Signing Devices — Ledger / Trezor / YubiKey / Mobile

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Re-evaluate this optional hardware-signing design after ADR-021's ConductorSeed disposition and the current approval/identity architecture are settled. If retained, create a current implementing spec and adapters with explicit device capability boundaries, degraded-mode behavior, modality audit evidence, and migration tests; otherwise supersede the ADR with the chosen credential/signing architecture.  
**Current state:** No current SigningDevice implementation or Ledger/Trezor/YubiKey/mobile hardware-signing adapters were located. ADR-022 therefore remains an accepted future/optional design, not a current authentication, authorization, HITL-approval, or signing dependency. Its original setup-wizard integration also depends on unresolved ADR-020/021 architecture.  
**ADR:** [ADR-022: Hardware Signing Devices — Ledger / Trezor / YubiKey / Mobile](../../../adr/ADR-022-hardware-signing.md)

## ADR-023: Agent Crypto Operations & Spending Policy

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile ADR-023 with ADR-021's later opt-in seed amendment and the current HITL/authorization architecture before any implementation. If crypto operations remain desired, create a current spec that preserves propose/sign/execute separation, bounded spending authority, explicit human escalation, and auditability without making seed/wallet infrastructure a baseline dependency; otherwise supersede this ADR.  
**Current state:** No CryptoOps/SpendingPolicy implementation was located. This remains an optional future capability. Its statement that the Conductor Seed is generated regardless is stale against ADR-021's later decision that seed/DID/wallet functionality is opt-in, so agents must not infer any current wallet, payment, signing, or crypto authority from this accepted ADR.  
**ADR:** [ADR-023: Agent Crypto Operations & Spending Policy](../../../adr/ADR-023-agent-crypto-ops.md)

## ADR-024: Agent Identity & Verifiable Credentials (DID + VC)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile this ADR with the canonical principal/workspace/delegation/Run identity model and ADR-021's opt-in seed amendment. If DID/VC remains desired, redefine and implement it explicitly as an optional federation/cryptographic-attestation layer over canonical runtime identities, with mappings and authority boundaries that prevent a DID from becoming an alternate authorization principal. Otherwise identify/create the successor decision and supersede ADR-024.  
**Current state:** No IdentityService, DID-document publication, or VC signing/verification implementation was located. Current runtime identity and authorization use canonical principals, Workspace scope, delegation identity, and Run provenance. ADR-024's claim that every conductor automatically has a seed-derived `did:key` is stale against ADR-021's later opt-in decision; DID/VC is therefore not current authentication or execution identity.  
**ADR:** [ADR-024: Agent Identity & Verifiable Credentials (DID + VC)](../../../adr/ADR-024-agent-identity-did-vc.md)

## ADR-026: Internal Trust Root — Local CA from Conductor Seed

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether a local/private PKI remains a current product requirement. If retained, redesign its root-key source and trust ceremony against the current baseline identity architecture so local TLS does not require optional ConductorSeed or DID/VC features; seed-derived CA may remain an explicit opt-in mode. Then create a current implementation/security test spec for name constraints, leaf rotation, device revocation, and zero-public-PKI operation. Otherwise supersede ADR-026.  
**Current state:** No LocalCA/TrustInstaller implementation was located. The accepted design depends on ADR-021 and ADR-024 as mandatory substrate, but those capabilities are currently unimplemented and ADR-021 was later amended to make seed/DID features optional. Therefore this ADR does not describe current TLS/authentication behavior and must not be treated as an active trust root by agents.  
**ADR:** [ADR-026: Internal Trust Root — Local CA from Conductor Seed](../../../adr/ADR-026-internal-trust-root.md)

## ADR-028: Admin / User Privilege Separation — Mandatory two-tier model

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Audit ADR-028 together with ADR-068 and the current Sentinel/PrivilegeGuard/HITL implementation. Preserve the structural invariants that agents cannot exceed their owning human's authority and privileged actions require explicit authorization/elevation, but evaluate completion against ADR-068's configurable roles, approver graph, self-elevation, scoped agent 2FA, budget ordering, and canonical principals rather than resurrecting obsolete seed/wallet/VC mechanics. Update/supersede stale ADR-028 acceptance criteria as needed after that reconciliation.  
**Current state:** ADR-068 explicitly amends rather than supersedes ADR-028: admin/user remain base roles, but the two-tier-only model, fixed admin approval path, and "full RBAC out of scope" decision are no longer current. Current production uses newer principal/authorization machinery, while ADR-068 itself remains Accepted after evidence reconciliation. ADR-028 is therefore an active foundational security principle whose detailed mechanics are partially stale.  
**ADR:** [ADR-028: Admin / User Privilege Separation — Mandatory two-tier model](../../../adr/ADR-028-privilege-separation.md)

## ADR-051: Tool approval gates — plan preview, impact-weighted escalation, learned trust

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create or identify a complete successor ADR for approval/elevation on the canonical Capability Binding → Invocation path, including the durable approval store/mechanism that actually shipped and ADR-068's RLPHD limits. Once that decision fully owns the replacement boundary, transition ADR-051 to `Superseded`. Do not reconnect the old unreachable ApprovalGate island.  
**Current state:** Human approval remains required architecture, but ADR-051's original implementation was unreachable and its counter-based learned-trust layer has been replaced by ADR-068's RLPHD model. Durable approval now exists at the Invocation boundary, while the current Binding/Invocation ADR/spec explicitly does not yet own all approval semantics. ADR-051 therefore remains Accepted pending a truthful successor.  
**ADR:** [ADR-051: Tool approval gates — plan preview, impact-weighted escalation, learned trust](../../../adr/ADR-051-tool-approval-gates.md)

## ADR-059: OAuth2 user authentication — real provider flow, layered over service-key authz

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite this proposal before acceptance so OAuth/OIDC authenticates a human into the canonical principal/Workspace-membership identity model rather than making HiveUser/session state a separate identity authority. Preserve Authorization Code + PKCE/state/OIDC verification, stable provider-subject linking, no privileged auto-provisioning, server-side secret storage, and separation of authentication from authorization. Define how human sessions and service credentials converge on the same canonical principal representation while retaining distinct authentication methods.  
**Current state:** The proposal correctly rejects the dangerous fabricating OAuth stub and specifies strong OAuth/OIDC mechanics, but its authN→authZ integration is anchored to the older HiveUser product model. Current convergence work treats canonical principals, Workspace authorization, service principals, delegation, and Run provenance as shared authority. Accepting ADR-059 unchanged would reintroduce a parallel user-identity source of truth.  
**ADR:** [ADR-059: OAuth2 user authentication — real provider flow, layered over service-key authz](../../../adr/ADR-059-oauth2-user-authentication.md)

## ADR-064: Comprehensive Secret Redaction

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the ADR's scope and lifecycle evidence. All 44 `maistro.security.redact` scenarios are recorded as reachable/passing, so add the actual proving tests to front matter and decide whether ADR-064 owns only the redaction primitive or the end-to-end "secrets never appear in logs/errors/recordings" boundary implied by its title/context. If end-to-end, add canonical logging/error/Run/Invocation evidence rather than legacy ADR-062 trajectory hooks. Promote only after that contract is unambiguous and evidenced.  
**Current state:** The redaction primitive itself is unusually mature: the ADR records all 44 acceptance scenarios as reachable and passing, including catalogue coverage and scaling benchmarks. The document still separates logging/error/trajectory integration from its implementation scope and has no `tests:` evidence in front matter, so an `Implemented` claim would currently be ambiguous under ADR-097/032.  
**ADR:** [ADR-064: Comprehensive Secret Redaction](../../../adr/ADR-064-secret-redaction.md)

## ADR-068: Unified Authorization & Elevation

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Treat ADR-068 as the current high-level authorization composition contract and reconcile its identity/signing assumptions with canonical principals and the fact that ConductorSeed/DID/wallet capabilities are optional/unimplemented. Audit and close the actual enforcement path for tier resolution, principal/owner authority intersection, approver graph, self-elevation vs agent-scoped 2FA, budget-before-gate ordering, durable approval state, and RLPHD hard limits. Promote only when end-to-end evidence supports the complete evaluation order.  
**Current state:** ADR-068 explicitly amends ADR-028/051 and supplies the current conceptual model: configurable roles/scopes, agent principals as subsets of owning-human authority, a gating-tier ladder, relational approvers, and CLASSIFY → AUTHORIZE → BUDGET → GATE → EXECUTE ordering. Its prior Implemented claim was rolled back because evidence was incomplete. Some cryptographic substrate wording still assumes mandatory seed/DID mechanisms that earlier ADRs no longer make baseline requirements.  
**ADR:** [ADR-068: Unified Authorization & Elevation](../../../adr/ADR-068-unified-authorization-and-elevation.md)

## ADR-072: Threat Model — assets, adversaries, trust boundaries

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Refresh the threat model against current canonical architecture and distinguish **enforced controls** from **accepted/planned controls**. Update protected assets/boundaries to include canonical principals and Workspace membership, Run/NodeRun/Attempt and Invocation evidence, Capability Bindings/providers, current credential routing, memory, audit, and governed model/harness egress. Remove or clearly mark non-baseline assumptions such as ConductorSeed as root-of-everything, DID-pinned federation, and microVM CodeRegistry execution until those are actually current.  
**Current state:** The core posture remains authoritative and valuable: malicious third-party code is the primary anchor, controls must be structural, untrusted-by-default, and fail-closed, with Warden/Sentinel at trust/effect boundaries. The defense map currently overstates several optional or unimplemented mechanisms, so agents could mistake intended defenses for enforced ones unless the model is refreshed.  
**ADR:** [ADR-072: Threat Model — assets, adversaries, trust boundaries](../../../adr/ADR-072-threat-model.md)
