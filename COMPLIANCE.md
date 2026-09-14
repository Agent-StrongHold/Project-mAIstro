# Maistro Engine Compliance Claims

**Scope:** This document describes technical controls in `maistro-engine` only. Stronghold owns hard tenant isolation, IdP integration, deployer obligations, and legal attestations.

**Evidence rule:** A status is a technical classification, not a legal conclusion. `implemented` is reserved for a control with current passing executable evidence, an immutable evidence URL and SHA-256, and an exact release digest. The registry currently has no such evidence, so no claim is green. Disabled, manual-only, never-run, stale, or failing checks cannot support `implemented`.

**Human ownership:** Legal interpretation and whether a control is legally sufficient remain human-owned. This checker verifies repository facts, schema shape, executable references, evidence provenance, verification dates, scope, and expiry only.

## Statuses

| Status | Meaning |
|---|---|
| `implemented` | Current executable control and passing immutable evidence are bound to the release digest. |
| `partially_implemented` | Some technical controls exist, but the full claim or release evidence is incomplete. |
| `documented` | The control is specified or mapped, without a complete executable claim. |
| `planned` | Future work; it must not be read as shipped control evidence. |
| `not_applicable` | Outside this engine's scope under the cited ownership decision. |
| `unverified` | The current release claim has not been established by immutable evidence. |

## Control Registry

<!-- compliance-registry:begin -->
| ID | Framework | Claim | Status | Owner | Scope | Last verification | Expires | Evidence |
|---|---|---|---|---|---|---|---|---|
| OWASP-AT-01 | OWASP Agentic Top 10 | Memory poisoning is bounded by content scanning, decay floors, and promotion gates. | partially_implemented | @engine-security | maistro-engine runtime; tenant policy remains Stronghold-owned | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-02 | OWASP Agentic Top 10 | Tool calls are subject to the Sentinel policy and validator boundary. | partially_implemented | @engine-security | maistro-engine tool-call boundary | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-03 | OWASP Agentic Top 10 | Privilege escalation is constrained by the authorization tier ladder. | partially_implemented | @engine-security | maistro-engine authorization primitives; deployer identity is product-owned | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-04 | OWASP Agentic Top 10 | Quota, rate-limit, and retry primitives limit resource overload. | partially_implemented | @engine-reliability | maistro-engine resource controls | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-05 | OWASP Agentic Top 10 | Circuit breakers, fallback, and retry controls reduce cascading failures. | partially_implemented | @engine-reliability | maistro-engine resilience primitives | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-06 | OWASP Agentic Top 10 | Caller authentication and agent identity lifecycle primitives address identity spoofing. | partially_implemented | @engine-security | maistro-engine authentication; signed registry loading is not claimed | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-07 | OWASP Agentic Top 10 | Builder contracts and structural review address misaligned objectives. | documented | @engine-governance | maistro-engine builder documentation; runtime reachability is not asserted | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-08 | OWASP Agentic Top 10 | Durable decision and event records provide accountability; signed decision VCs remain future work. | planned | @engine-security | maistro-engine audit and event records | not recorded | 2027-08-25 | none |
| OWASP-AT-09 | OWASP Agentic Top 10 | Elevation and approval interfaces are specified for human oversight. | documented | @engine-security | maistro-engine approval primitives; no deployer UI claim | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-10 | OWASP Agentic Top 10 | Skill scanning and sandbox selection are present; hardware-VM conformance is not yet evidenced. | planned | @engine-security | maistro-engine untrusted-code boundary | not recorded | 2027-08-25 | none |
| NIST-GOVERN | NIST AI RMF | Governance, accountability, workforce guidance, oversight, and lifecycle controls are mapped. | partially_implemented | @engine-governance | maistro-engine governance artifacts and security primitives | 2026-08-25 | 2027-08-25 | none |
| NIST-MAP | NIST AI RMF | Context, categorization, capabilities, impact, and prioritization are documented. | documented | @engine-governance | maistro-engine threat and capability documentation | 2026-08-25 | 2027-08-25 | none |
| NIST-MEASURE | NIST AI RMF | Testing, observability, mutation checks, and learning feedback are mapped to measurement. | partially_implemented | @engine-quality | maistro-engine quality and observability gates | 2026-08-25 | 2027-08-25 | none |
| NIST-MANAGE | NIST AI RMF | Risk treatment, allocation, deployment checks, and response documentation are mapped. | partially_implemented | @engine-governance | maistro-engine runtime and CI controls | 2026-08-25 | 2027-08-25 | none |
| EU-AI-ACT-ART-09 | EU AI Act | Risk-management documentation is present for engine controls. | documented | @engine-governance | engine documentation only; legal sufficiency is human-owned | 2026-08-25 | 2027-08-25 | none |
| EU-AI-ACT-ART-10 | EU AI Act | Memory scopes, PII filtering, and log redaction are mapped to data governance. | partially_implemented | @engine-privacy | engine data controls; tenant obligations remain Stronghold-owned | 2026-08-25 | 2027-08-25 | none |
| EU-AI-ACT-ART-11 | EU AI Act | Technical documentation is represented by the ADR and project documentation set. | documented | @engine-governance | maistro-engine technical documentation | 2026-08-25 | 2027-08-25 | none |
| EU-AI-ACT-ART-12 | EU AI Act | Audit and event record primitives exist; retention policy is not a verified engine-wide claim. | partially_implemented | @engine-security | maistro-engine audit and event records | 2026-08-25 | 2027-08-25 | none |
| EU-AI-ACT-ART-13 | EU AI Act | Warden flag responses expose technical reasons for blocked or flagged content. | partially_implemented | @engine-security | maistro-engine response primitives | 2026-08-25 | 2027-08-25 | none |
| EU-AI-ACT-ART-14 | EU AI Act | Deployer-facing human oversight is deferred to the importing product. | not_applicable | @stronghold-compliance | Stronghold deployer surface, outside maistro-engine | not recorded | 2027-08-25 | none |
| EU-AI-ACT-ART-15 | EU AI Act | Accuracy, robustness, and cybersecurity controls are not verified for a release digest by this registry. | unverified | @engine-security | maistro-engine release claim; legal interpretation is human-owned | not recorded | 2027-08-25 | none |
| EU-AI-ACT-ART-17 | EU AI Act | Quality-management CI controls are not verified for a release digest by this registry. | unverified | @engine-governance | maistro-engine release claim; legal interpretation is human-owned | not recorded | 2027-08-25 | none |
| EU-AI-ACT-ART-26 | EU AI Act | Deployer obligations are deferred to the importing product. | not_applicable | @stronghold-compliance | Stronghold deployer surface, outside maistro-engine | not recorded | 2027-08-25 | none |
| SOC2-SECURITY | SOC 2 Type II | Security primitives are mapped; an auditor attestation is not represented here. | partially_implemented | @engine-security | maistro-engine controls; SOC 2 audit remains deployment-owned | 2026-08-25 | 2027-08-25 | none |
| SOC2-AVAILABILITY | SOC 2 Type II | Health checks and resilience primitives are mapped to availability. | partially_implemented | @engine-reliability | maistro-engine availability primitives | 2026-08-25 | 2027-08-25 | none |
| SOC2-PROCESSING-INTEGRITY | SOC 2 Type II | Contract tests and quality gates are mapped to processing integrity; runtime reachability is not asserted. | partially_implemented | @engine-quality | maistro-engine build and test controls | 2026-08-25 | 2027-08-25 | none |
| SOC2-CONFIDENTIALITY | SOC 2 Type II | Soft scopes and log redaction exist; hard tenant confidentiality is product-owned. | partially_implemented | @engine-privacy | maistro-engine soft scopes and log output | 2026-08-25 | 2027-08-25 | none |
| SOC2-PRIVACY | SOC 2 Type II | PII filtering and sensitivity tiers are mapped to privacy controls. | partially_implemented | @engine-privacy | maistro-engine PII and sensitivity primitives | 2026-08-25 | 2027-08-25 | none |
<!-- compliance-registry:end -->

## Maintenance

`quality/compliance-registry.json` is the source of truth. Run `python scripts/check-compliance.py` after changing either file; it rejects unknown or duplicate IDs, malformed table rows, missing references, missing owners, invalid dates, expired green evidence, and registry/document drift.

CI validates the registry on every change. The release workflow runs the same check with `--require-release-evidence --release-digest <tag commit>`, which fails closed until every release-required claim has passing evidence bound to that exact immutable digest.

An evidence record must identify its control ID and exactly repeat that control's executable control and test references. The evidence link must identify an immutable GitHub Actions artifact or run in this repository, carry its SHA-256, record the observed date and result, and name the exact release commit digest. Green `implemented` evidence must use an artifact URL; the checker queries GitHub for the artifact digest, workflow run conclusion, workflow path, release head SHA, and expiry, failing closed when any provenance is missing or mismatched. It derives workflow enabled/manual-only state from the checked-in workflow rather than trusting registry booleans, rejects observations older than 90 days for green claims, and verifies the release digest exists in the checkout. Every `test_refs` entry must be an existing Python test module under `tests/`, a package `tests/` directory, or `formal/`, with a `test_` filename; a path alone is not evidence that the test ran.
