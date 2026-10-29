# Legacy / Early Product Specs

Progressive-disclosure index for early sequential specs whose concrete architecture often predates the August 2026 canonical Workspace/Run/Capability model.

These specs are not deleted history. Their useful requirements should be migrated into current canonical specs; obsolete execution/identity/compatibility mechanisms should not be implemented merely because they remain Proposed.

## SPEC-001: Bouncer

**Status:** AC Defined  
**Next steps:** Reconcile the useful inbound-content screening requirements with canonical Warden/Sentinel and current payload-normalization specs. Do not treat the old Bouncer agent as a second security authority. File/file-attachment integrity, decompression/resource limits, trust labeling, and injection screening should land at current ingress boundaries.  
**Current state:** This contains substantial security requirements, but its named Conductor/Bouncer implementation predates the current Warden/Sentinel boundary and has stale lifecycle metadata: `implemented` exists while status remains AC Defined and tests are empty.  
**SPEC:** [SPEC-001](../../../specs/SPEC-001-bouncer.md)

## SPEC-002: Email channel

**Status:** Proposed  
**Next steps:** If email remains desired, rewrite as a canonical ingress adapter: authenticate sender intent, structurally normalize content, Warden-scan untrusted text, admit a canonical Run only after out-of-band confirmation, and retain raw email only as an audit artifact. Remove Conductor-specific/Bouncer/task assumptions.  
**Current state:** The hardened ingestion amendment is directionally strong, but no current canonical email channel is evidenced.  
**SPEC:** [SPEC-002](../../../specs/SPEC-002-email-channel.md)

## SPEC-003: Secrets migration

**Status:** Proposed  
**Next steps:** Replace product-SKU/vault-era assumptions with current credential/secret ownership. Inventory every production secret source, prohibit tracked/plaintext secret material, fail closed for required secrets, and route provider credentials through canonical credential resolution. Keep optional seed-derived vault identity optional.  
**Current state:** Useful security requirements remain, but many named call sites and Stronghold/Conductor product distinctions are stale.  
**SPEC:** [SPEC-003](../../../specs/SPEC-003-secrets-migration.md)

## SPEC-004: General hooks system

**Status:** Proposed  
**Next steps:** Do not implement arbitrary host shell hooks as written. If extensibility is still needed, express hooks as explicitly installed/authorized capability providers executed under ADR-093 sandbox and canonical Invocation with bounded resources and sanitized inputs.  
**Current state:** Direct executable files under a user directory create a parallel effect/execution surface inconsistent with current capability and sandbox architecture.  
**SPEC:** [SPEC-004](../../../specs/SPEC-004-hooks-system.md)

## SPEC-005: Medley full

**Status:** Proposed  
**Next steps:** Rewrite plugin install/trust/versioning around current Capability Provider provenance, explicit installation, content hashes/signatures, sandbox policy, and canonical Bindings. DID/VC must not be mandatory unless the newer identity architecture explicitly chooses it.  
**Current state:** The supply-chain problem remains valid; the Medley+DID/VC mechanism predates ADR-081226-6b46 and ADR-083.  
**SPEC:** [SPEC-005](../../../specs/SPEC-005-clawhub-full.md)

## SPEC-006: Stress rehearsal

**Status:** Proposed  
**Next steps:** Preserve controlled fault-injection goals but run scenarios through the canonical test/sandbox/Run infrastructure. Replace SQLite/reactor assumptions and require isolation consistent with ADR-093 rather than a generic subprocess.  
**Current state:** Chaos/resilience testing is useful; the proposed execution/storage topology is obsolete.  
**SPEC:** [SPEC-006](../../../specs/SPEC-006-stress-rehearsal.md)

## SPEC-007: Collective unconscious

**Status:** Proposed  
**Next steps:** Do not implement until cross-user/federated memory sharing has a current privacy, consent, principal, and federation design. Reuse explicit promotion/sharing semantics rather than a magical cross-tenant T7 pool.  
**Current state:** This is speculative and depends on optional/deferred DID/Lightning federation.  
**SPEC:** [SPEC-007](../../../specs/SPEC-007-collective-unconscious.md)

## SPEC-008: Agent-to-agent networking

**Status:** Proposed  
**Next steps:** Replace direct agent RPC with the current delegation model: local strategy delegation remains inside a Node, independent delegated work becomes child Runs, remote fulfillment uses governed capability/provider effects, and authority only narrows.  
**Current state:** The requirement has been overtaken by ADR-082426-6201, canonical child Runs, and current delegation work.  
**SPEC:** [SPEC-008](../../../specs/SPEC-008-agent-networking.md)

## SPEC-009: Setup wizard

**Status:** Proposed  
**Next steps:** Reconcile with SPEC-180/maistro-bootstrap and decide whether browser-first onboarding is still required. Do not preserve the old mandatory seed/DID/two-user ceremony unless current identity decisions require it.  
**Current state:** A real bootstrap package exists, but not this original browser-first ceremony.  
**SPEC:** [SPEC-009](../../../specs/SPEC-009-setup-wizard.md)

## SPEC-010: SQLite singleton

**Status:** Proposed  
**Next steps:** Supersede with current PostgreSQL ownership/pool architecture. Do not build a new SQLite write-serialization authority for canonical durable state.  
**Current state:** Canonical durable storage has moved to PostgreSQL and ADR-082926-730d owns asyncpg pool lifecycle.  
**SPEC:** [SPEC-010](../../../specs/SPEC-010-sqlite-singleton.md)

## SPEC-011: Vault

**Status:** Proposed  
**Next steps:** Reconcile the useful encrypted-secret-store contract with current credential/secret architecture and deployment model. Avoid making optional ConductorSeed identity mandatory.  
**Current state:** This is an older personal-Conductor vault design, not proof of the current production secret path.  
**SPEC:** [SPEC-011](../../../specs/SPEC-011-vault.md)

## SPEC-012: Privilege separation

**Status:** Proposed  
**Next steps:** Rewrite against canonical principals, Workspace/Project scoped grants/denies, ADR-068, durable HITL, and ADR-090726-9a4e crypto-bound approvals. Remove users.toml, mandatory two-human install, wallet/VC elevation, and legacy UsersStore assumptions.  
**Current state:** The structural anti-escalation requirement survives; the mechanism does not.  
**SPEC:** [SPEC-012](../../../specs/SPEC-012-privilege-separation.md)

## SPEC-013: 1kHz reactor

**Status:** Proposed  
**Next steps:** Do not implement as a universal runtime loop. Map event ingestion to ADR-086 durable triggers, recurrence to canonical Run admission, and long-running work to the canonical Run consumer/ExecutionRuntime.  
**Current state:** This predates the durable event/Run architecture and would recreate a competing scheduler/executor.  
**SPEC:** [SPEC-013](../../../specs/SPEC-013-1khz-reactor.md)

## SPEC-014: LiteLLM free-tier auto-configuration

**Status:** Proposed  
**Next steps:** Preserve provider onboarding, privacy disclosure, local-only operation, and graceful provider failure, but route all model selection/credentials/fallback through the current Provider/Binding/Invocation and credential-routing architecture.  
**Current state:** Current model routing/fallback has evolved far beyond this setup-time LiteLLM-specific design.  
**SPEC:** [SPEC-014](../../../specs/SPEC-014-litellm-freetier.md)

## SPEC-015: Hyperagent Graph Runtime

**Status:** Proposed  
**Next steps:** Supersede with ADR-081226-69ee + a66b + 1f7c + 6b46. Migrate any still-useful imported-harness/delegation/budget requirements into current specs rather than implementing AgentSpec as the universal node/runtime.  
**Current state:** The canonical Graph/Node/Run architecture explicitly replaced this execution model.  
**SPEC:** [SPEC-015](../../../specs/SPEC-015-hyperagent-graph-runtime.md)

## SPEC-016: Networking and identity substrate

**Status:** Proposed  
**Next steps:** Split networking transport from authentication authority. If substrate plugins remain useful, implement reachability/TLS adapters without trusting arbitrary substrate headers as canonical principals.  
**Current state:** No current substrate implementation was found during the ADR audit; authentication has moved to canonical principals/session/service identity.  
**SPEC:** [SPEC-016](../../../specs/SPEC-016-tailscale-native.md)

## SPEC-017: Electrum server

**Status:** Proposed  
**Next steps:** None for M1-M4 unless optional Bitcoin capability is reactivated. Reconcile with current provider/plugin/sandbox/secret architecture before implementation.  
**Current state:** Its parent ADR is Deferred.  
**SPEC:** [SPEC-017](../../../specs/SPEC-017-electrum-server.md)

## SPEC-018: Lightning federation

**Status:** Proposed  
**Next steps:** None for M1-M4 unless federation/Lightning is reactivated. Do not implement its DID/VC/Lightning identity assumptions as baseline.  
**Current state:** Its parent ADR is Deferred and several dependencies remain optional/unimplemented.  
**SPEC:** [SPEC-018](../../../specs/SPEC-018-lightning-federation.md)

## SPEC-019: Human-as-node

**Status:** Proposed  
**Next steps:** Rewrite around canonical Human/HITL Node semantics, durable deadline/cancellation, principal identity, and channel providers. Human response must be untrusted input, but signed-VC audit and reactor/channel assumptions are stale.  
**Current state:** The current HITL architecture is materially newer and already has durable timeout/cancel semantics.  
**SPEC:** [SPEC-019](../../../specs/SPEC-019-human-as-node.md)

## SPEC-020: Node + Graph Designer

**Status:** Proposed  
**Next steps:** Rebuild requirements around canonical NodeTemplate/GraphTemplate, Project Graph objects, Workspace authorization, and current Design Studio/Workspace UI. Remove admin-signature/VC and legacy node-type assumptions.  
**Current state:** The visual composition need remains plausible; the underlying model and security authority have changed.  
**SPEC:** [SPEC-020](../../../specs/SPEC-020-node-graph-designer.md)
