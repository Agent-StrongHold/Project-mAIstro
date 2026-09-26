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
| OWASP-AT-01 | OWASP Agentic Top 10 | Memory poisoning is bounded by content scanning, decay floors, and promotion gates; Warden scan windows and timeouts bound pathological regex work on the product path. | partially_implemented | @engine-security | maistro-engine runtime; tenant policy remains Stronghold-owned | 2026-08-25 | 2027-08-25 | none |
| OWASP-AT-02 | OWASP Agentic Top 10 | Tool calls are subject to the Sentinel policy and validator boundary; the post-call Warden scan that backs PII masking runs on the product path with bounded windows. | partially_implemented | @engine-security | maistro-engine tool-call boundary | 2026-08-25 | 2027-08-25 | none |
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

## Product-path evidence for security claims

The OWASP-AT-01 and OWASP-AT-02 rows above are exercised at the Sentinel output
boundary and on the canonical execution paths, rather than inferred from
Warden constants: the real Warden is invoked by the output gate against a
catastrophic regex in overlapping windows, a multi-window benign result, a
padded semantic instruction whose action and object cross a window boundary,
and the product-path capture/object ordering regression
(`packages/maistro-core/tests/security/test_sentinel_policy.py`). The same
defenses run behind `build_output_security_gate` through
`MasterOrchestrator.execute` — timeout fail-closed, windowed reject and
fallback searches, static refusal in the canonical Run projection
(`packages/maistro-core/tests/orchestrator/test_output_security_gate.py`) —
and through the production governed tool executor in `Agent.handle`, since
`BaseAgent` always sets `security_pipeline=True`
(`packages/maistro-core/tests/agents/test_base.py`).
The accelerated/fallback pattern contract includes a complete Warden verdict
comparison in
`packages/maistro-core/tests/security/test_warden_regex_equivalence.py`.
PII/secret handling is also exercised on `Sentinel.post_call`, `DirectStrategy`,
and `ReactStrategy`: `test_sentinel_policy.py` proves the raw credential is not
present in either output or `PIIMatch` metadata, while the strategy tests prove
a missing PII-filter dependency blocks output instead of returning it
unsanitized; the governed-executor tests prove the same masking and fail-closed
contract on the production agent seam, including the RCA pipeline recording the
blocked tool call. These executed product paths — not the constants alone — are
the evidence for the registry claims above; the constants remain implementation
details.

## Maintenance

`quality/compliance-registry.json` is the source of truth. Run `python scripts/check-compliance.py` after changing either file; it rejects unknown or duplicate IDs, malformed table rows, missing references, missing owners, invalid dates, expired green evidence, and registry/document drift. Every `implemented`, `partially_implemented`, or `documented` claim must carry both a `last_verified` date and an `expires` date: evidence without an expiry could never go stale, so a null expiry fails the check instead of being trusted forever.

CI validates the registry on every change. The release workflow runs the same check with `--require-release-evidence --release-digest <tag commit> --resolve-release-evidence --resolved-output release-compliance.json`. That mode fails closed for every `release_required` control unless it is `implemented` and has current evidence bound to the exact release digest; non-green statuses therefore block release rather than being silently promoted to green. The current registry intentionally fails this release-mode check because its Article 15 and 17 controls are `unverified` and have no evidence.

### Post-commit release binding

A commit cannot contain its own SHA or an artifact ID created after it. Do not edit the source registry to insert the current commit's digest. Instead:

1. A control owner reviews the technical claim, scope, executable `control_refs`, and complete `test_refs`, then explicitly sets optional `verification_requested: true` in the registry. A request may accompany `unverified` or `partially_implemented`; it is **not** a seventh status or green evidence. Requests default to false. Planned, documented, and out-of-scope controls cannot request automatic promotion. This repair requests no verification and does not claim that existing broad regulatory mappings are test-complete.
2. Commit the reviewed registry and matching non-green document. Automatic pushes to `main`, `develop`, or `integration` execute requested controls in `compliance-evidence.yml`, using `scripts/produce-compliance-evidence.py`. Every `test_refs` entry must name an existing Python `test_` module under `tests/`, a package `tests/` directory, or `formal/`. Empty suites and nonzero test exits fail. The producer writes control-bound manifests and uploads `compliance-evidence-<commit SHA>`; it never edits source statuses. Wait for that branch run to complete before tagging that exact commit. `integration` supports release candidates per ADR-073126-c4e1.
3. The release guard validates the source registry/document and proves they are unchanged tracked files at the tag's checkout HEAD. It resolves only explicit requests against a completed successful **push** run of the evidence workflow at that exact SHA. Manual dispatch is diagnostic, not release evidence. It downloads the immutable artifact, checks its actual SHA-256 against GitHub, and constructs a release-only registry with artifact-ID URLs and manifest hashes. No post-run source commit is needed.
4. The normal fail-closed evidence validator checks every derived green claim: control ID and exact control/test references, passing execution and exit codes, manifest observation date, artifact/run/workflow provenance, live enabled state, expiry, and freshness (at most 90 days, never extending the owner's expiry). Missing or failing evidence, disabled or manual-only workflows, stale dates, and unrequested non-green required controls still block publication. No release requirements are waived. The guard uploads `release-compliance.json` only on success; the sole publisher `release.yml` attaches that validated registry to the release with SHA256SUMS. Source COMPLIANCE.md remains the conservative pre-release view.

An evidence record identifies its control ID and exactly repeats its executable references. Historical green source records may use direct immutable Actions artifact URLs, or commit-bound workflow locators (`blob/<digest>/.github/workflows/...`) resolved to successful runs and deterministic artifact names. Direct records carry SHA-256; locators obtain it from GitHub. All green evidence requires an executed-test attestation, not just a generic green job. API failures, expired/deleted artifacts, and missing provenance fail closed; regenerate evidence before release if the 90-day Actions retention has elapsed. Automation verifies factual technical evidence only; owner review, downstream compliance interpretation, and legal sufficiency remain human responsibilities.
