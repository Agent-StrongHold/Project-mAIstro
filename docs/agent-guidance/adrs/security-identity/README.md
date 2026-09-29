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
