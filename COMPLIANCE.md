# Maistro Engine Compliance Claims

**Scope:** This document describes technical controls in `maistro-engine` only. Stronghold owns hard tenant isolation, IdP integration, deployer obligations, and legal attestations.

**Evidence rule:** A status is a technical classification, not a legal conclusion. `implemented` is reserved for a control with current passing executable evidence, an immutable evidence URL and SHA-256, and an exact release digest. The registry currently has no such evidence, so no claim is green. Disabled, manual-only, never-run, stale, or failing checks cannot support `implemented`.

**Human ownership:** Legal interpretation and whether a control is legally sufficient remain human-owned. This checker verifies repository facts, schema shape, executable references, evidence provenance, verification dates, scope, and expiry only.

## Statuses

| `implemented` | Technical control is implemented with current automated evidence |
| `partially_implemented` | Some implementation or execution seams remain incomplete |
| `documented` | The control is specified or mapped, but not asserted as an implementation |
| `planned` | The control is planned or specified but not implemented |
| `not_applicable` | Deferred to the importing product (Stronghold, per ADR-019) |
| `unverified` | No current evidence supports a stronger state |

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

The marker-delimited registry above is the release-bound control view owned by `quality/compliance-registry.json` and validated by `scripts/check-compliance.py`. The detailed mapping tables below are the engine's typed evidence view: every cited artifact is backed by an evidence record in `docs/compliance/claims.json`, validated by `scripts/check_compliance.py`. The two registries use disjoint control-ID namespaces and are validated independently; a row that is green in neither view is not green.

## OWASP Agentic Top 10

| ID | Risk | Engine control | Test path | Status |
|---|---|---|---|---|
| **AT-01** | Memory poisoning | Warden boundary scan (`security/warden/detector.py`) + episodic memory decay/weight floors (ADR-013 scopes) + learning promotion gate | `packages/maistro-core/tests/security/warden/test_detector.py`; `packages/maistro-core/tests/memory/episodic/test_decay.py`; `packages/maistro-core/tests/memory/learnings/test_promoter_gate.py` | partially_implemented |
| **AT-02** | Tool misuse | Sentinel PDP/PEP at the tool-call boundary (ADR-073) — `security/sentinel/policy.py`, `security/sentinel/validator.py` — + dangerous-command/tool detection (`security/dangerous_tools.py`). **Reversibility classification (`tools/reversibility_registry.py`, ADR-050) is NOT operative** — `ReversibilityRegistry` is never constructed; `Sentinel.resolve_tier` branches on a caller-supplied `reversibility` string defaulting to `"reversible"` and never consults the registry (#346) | `packages/maistro-core/tests/security/test_sentinel_policy.py`; `packages/maistro-core/tests/security/test_sentinel_validator.py`; `formal/models/test_dangerous_tools.py`; `formal/models/test_sentinel_policy.py`; `formal/models/test_sentinel_validator.py` | partially_implemented |
| **AT-03** | Privilege compromise | ADR-068 tier ladder (open → role/team-auto → self-elevation → delegated-approval → admin-elevation → blocked), `security/sentinel/elevation.py`, admin/user1 privilege separation (`privilege.py`, SPEC-012) | `packages/maistro-core/tests/security/test_authz_tier_ladder.py`; `packages/maistro-core/tests/security/test_elevation_grants.py`; `packages/maistro-core/tests/privilege/test_privilege.py` | partially_implemented |
| **AT-04** | Resource overload | Quota tracker (`quota/tracker.py`) + per-key rate limiter (`security/rate_limiter.py`) + circuit breakers / retry / fallback (ADR-038, `resilience/`) | `packages/maistro-core/tests/quota/test_tracker.py`; `packages/maistro-core/tests/security/test_rate_limiter.py`; `packages/maistro-core/tests/test_circuit_breaker.py`; `packages/maistro-core/tests/resilience/test_retry_policy.py` | partially_implemented |
| **AT-05** | Cascading failures | ADR-038 reliability primitives — circuit-breaker state machine + `Fallback[T]` + retry budgets — `resilience/`, `agents/circuit_breaker.py`. **ADR-038's SLO / error-budget burn-rate throttling is NOT implemented**; cascading-failure defence rests on the breaker, fallback and retry layers | `packages/maistro-core/tests/resilience/test_fallback.py`; `packages/maistro-core/tests/resilience/test_rate_coordination.py`; `packages/maistro-core/tests/test_circuit_breaker.py` | planned |
| **AT-06** | Identity spoofing | **Signed code-registry entries (`code_registry/verify.py`, ADR-069/SPEC-257) are NOT operative** — `CodeRegistry.register()`, which enforces Ed25519 verification, has no production callers; no code is signature-checked at load (#346). Operative: JWT/composite auth (`security/auth_jwt.py`, `security/auth_composite.py`) + agent identity lifecycle (`identity/lifecycle.py`) | `packages/maistro-core/tests/security/test_auth_jwt.py`; `packages/maistro-core/tests/security/test_auth_composite.py`; `packages/maistro-core/tests/code_registry/test_registry.py`; `packages/maistro-core/tests/identity/test_lifecycle.py`; `formal/models/test_jwt_auth.py`; `formal/models/test_composite_auth.py` | partially_implemented |
| **AT-07** | Misaligned objectives | Builders pipeline verification (spec → tests → code → review) + structural-awareness review gate that hard-fails on a deterministic CRITICAL finding even when the LLM reviewer says "APPROVED" (ADR-032 contracts-as-acceptance-criteria) | `packages/maistro-core/tests/builders/test_structural_gate.py`; `packages/maistro-core/tests/builders/test_pipeline_spec_flow.py` | partially_implemented |
| **AT-08** | Repudiation / lack of accountability | Sentinel decision audit (`security/sentinel/audit.py`, signed-VC intent per ADR-073) + durable event log (`events/`, ADR-037) | `packages/maistro-core/tests/security/sentinel/test_audit.py`; `packages/maistro-core/tests/events/test_durable_log.py` | partially_implemented |
| **AT-09** | Overreliance / lack of human oversight | ADR-068 elevation ladder (self-elevation / scoped-2FA / delegated-approval) + plan-approval gate (`tools/approval/gate.py`, ADR-051) | `packages/maistro-core/tests/tools/test_approval_gate.py`; `packages/maistro-core/tests/security/test_elevation_grants.py` | partially_implemented |
| **AT-10** | Supply-chain (skills / MCP / model / dependency) | ADR-093 sandbox isolation (microVM required for untrusted code, Docker-socket sandbox deprecated) + skill trust tiers, import security scan, and body-size cap (`skills/parser.py`, `skills/import_pipeline.py`) + signed code-registry entries (ADR-069) | `packages/maistro-core/tests/skills/test_import_pipeline.py`; `packages/maistro-core/tests/skills/test_parser.py`; `packages/maistro-core/tests/sandbox/test_selector.py`; `packages/maistro-core/tests/sandbox/backends/test_fake.py`; `packages/maistro-core/tests/code_registry/test_registry.py` | partially_implemented |

### OWASP gaps to close

- **AT-06**: agent-to-agent DID/VC signing (ADR-072's "tamper-evidence, open, ADR-068" line) is not yet a distinct module — `gap-impl`.
- **AT-08**: signed-VC decision records (ADR-073 acceptance criterion) are not implemented; the audit log itself is — `gap-impl` on signing only.
- **AT-10**: SPEC-190's microVM conformance/escape test suite is referenced by ADR-093 but not present in `formal/` or `packages/maistro-core/tests/` yet — `gap-test`.

## Maintenance

`quality/compliance-registry.json` is the source of truth. Run `python scripts/check-compliance.py` after changing either file; it rejects unknown or duplicate IDs, malformed table rows, missing references, missing owners, invalid dates, expired green evidence, and registry/document drift. Every `implemented`, `partially_implemented`, or `documented` claim must carry both a `last_verified` date and an `expires` date: evidence without an expiry could never go stale, so a null expiry fails the check instead of being trusted forever.

CI validates the registry on every change. The release workflow runs the same check with `--require-release-evidence --release-digest <tag commit> --resolve-release-evidence --resolved-output release-compliance.json`. That mode fails closed for every `release_required` control unless it is `implemented` and has current evidence bound to the exact release digest; non-green statuses therefore block release rather than being silently promoted to green. The current registry intentionally fails this release-mode check because its Article 15 and 17 controls are `unverified` and have no evidence.

### Post-commit release binding

A commit cannot contain its own SHA or an artifact ID created after it. Do not edit the source registry to insert the current commit's digest. Instead:

1. A control owner reviews the technical claim, scope, executable `control_refs`, and complete `test_refs`, then explicitly sets optional `verification_requested: true` in the registry. A request may accompany `unverified` or `partially_implemented`; it is **not** a seventh status or green evidence. Requests default to false. Planned, documented, and out-of-scope controls cannot request automatic promotion. This repair requests no verification and does not claim that existing broad regulatory mappings are test-complete.
2. Commit the reviewed registry and matching non-green document. Automatic pushes to `main`, `develop`, or `integration` execute requested controls in `compliance-evidence.yml`, using `scripts/produce-compliance-evidence.py`. Every `test_refs` entry must name an existing Python `test_` module under `tests/`, a package `tests/` directory, or `formal/`. Empty suites and nonzero test exits fail. The producer writes control-bound manifests and uploads `compliance-evidence-<commit SHA>`; it never edits source statuses. Wait for that branch run to complete before tagging that exact commit. `integration` supports release candidates per ADR-073126-c4e1.
3. The release guard validates the source registry/document and proves they are unchanged tracked files at the tag's checkout HEAD. It resolves only explicit requests against a completed successful **push** run of the evidence workflow at that exact SHA. Manual dispatch is diagnostic, not release evidence. It downloads the immutable artifact, checks its actual SHA-256 against GitHub, and constructs a release-only registry with artifact-ID URLs and manifest hashes. No post-run source commit is needed.
4. The normal fail-closed evidence validator checks every derived green claim: control ID and exact control/test references, passing execution and exit codes, manifest observation date, artifact/run/workflow provenance, live enabled state, expiry, and freshness (at most 90 days, never extending the owner's expiry). Missing or failing evidence, disabled or manual-only workflows, stale dates, and unrequested non-green required controls still block publication. No release requirements are waived. The guard uploads `release-compliance.json` only on success; the sole publisher `release.yml` attaches that validated registry to the release with SHA256SUMS. Source COMPLIANCE.md remains the conservative pre-release view.

## NIST AI Risk Management Framework (AI RMF)

Reference: NIST AI 100-1, NIST AI 100-2 (Generative AI Profile).

### Govern
| Function | Engine control | Status |
|---|---|---|
| GOVERN-1 (Policies, processes, structures) | Sentinel declarative policy layer, DB-backed + RBAC-editable + YAML/JSON export (ADR-073) | partially_implemented |
| GOVERN-2 (Accountability) | Sentinel decision audit (`security/sentinel/audit.py`) + ADR-037 event log | partially_implemented |
| GOVERN-3 (Workforce / culture) | `CLAUDE.md`, ADR ladder (`docs/adr/`) | documented |
| GOVERN-4 (Engagement / oversight) | ADR-068 elevation ladder + approval gate (`tools/approval/gate.py`) | partially_implemented |
| GOVERN-5 (Lifecycle) | Front-matter status lifecycle (ADR-031, enforced by `maistro-registry` CI, `registry.yml`) | partially_implemented |

### Map

| Function | Engine control | Status |
|---|---|---|
| MAP-1 (Context) | ADR-072 threat model (assets, adversaries, trust boundaries) | documented |
| MAP-2 (Categorization) | OWASP Agentic Top 10 mapping (this document) | documented |
| MAP-3 (Capabilities) | `maistro.capabilities` slot/provider registry (SPEC-184) | partially_implemented |
| MAP-4 (Risk impact) | ADR-072 asset/adversary tables; this document | documented |
| MAP-5 (Risk priority) | ADR-072 "Adversaries (ranked)" list | documented |

### Measure

| Function | Engine control | Status |
|---|---|---|
| MEASURE-1 (Identification) | Builders pipeline (spec → tests → code → review, `builders/`) + structural-awareness gate ; evidence: `packages/maistro-core/tests/builders/test_structural_gate.py` | partially_implemented |
| MEASURE-2 (Tracking) | ADR-037 observability (traces/metrics/logs/events) + ADR-055 replay ; evidence: `packages/maistro-core/tests/observability/test_tracing.py`; `packages/maistro-core/tests/observability/test_replay.py` | partially_implemented |
| MEASURE-3 (Effectiveness) | Mutation testing gate (`mutation.yml` CI workflow) | partially_implemented |
| MEASURE-4 (Feedback) | Learning promotion pipeline (`memory/learnings/promoter.py`) ; evidence: `packages/maistro-core/tests/memory/learnings/test_promoter.py` | partially_implemented |

### Manage

| Function | Engine control | Status |
|---|---|---|
| MANAGE-1 (Risk treatment) | Warden/Sentinel boundary scanning (ADR-073) + ADR-038 circuit breakers | partially_implemented |
| MANAGE-2 (Allocation) | Quota tracker (`quota/tracker.py`) + router scarcity-based cost ; evidence: `packages/maistro-core/tests/quota/test_tracker.py` | partially_implemented |
| MANAGE-3 (Pre-deployment) | CI gate stack (`ci.yml`, `quality.yml`, `security.yml`, `formal-conformance.yml`, `mutation.yml`, `cage-guard.yml`) | partially_implemented |
| MANAGE-4 (Documentation / response) | This document + `SECURITY.md` + Sentinel audit log | planned |

## EU AI Act (High-risk systems)

Reference: Regulation (EU) 2024/1689, Articles 9–15, 17, 26.

| Article | Requirement | Engine control | Evidence path | Status |
|---|---|---|---|---|
| **Art. 9** | Risk-management system | ADR-072 threat model + this COMPLIANCE.md | docs/adr/ADR-072-threat-model.md | documented |
| **Art. 10** | Data governance | Memory scope axes (global→org→team→user→agent→session, ADR-019 Decision 7) + Sentinel PII filter (`security/sentinel/pii_filter.py`) + secret redaction on both log pipelines (`security/redact.py` installed by `security/log_redaction.py`, ADR-064) | `formal/models/test_memory_scopes.py`; `formal/models/test_pii_filter.py`; `packages/maistro-core/tests/security/test_redact.py`; `packages/maistro-core/tests/security/test_log_redaction.py` | partially_implemented |
| **Art. 11** | Technical documentation | ADR ladder (`docs/adr/`, 100+ ADRs) + `CLAUDE.md` | CLAUDE.md | documented |
| **Art. 12** | Record-keeping | Sentinel decision audit + durable event log (`events/`) | packages/maistro-core/tests/events/test_durable_log.py | partially_implemented |
| **Art. 13** | Transparency to users | Warden flag-and-warn responses (`security/warden/flag_response.py`) surface why content was blocked/flagged | `formal/models/test_flag_response.py` | partially_implemented |
| **Art. 14** | Human oversight | ADR-068 elevation ladder (self-elevation / scoped-2FA / delegated / admin) is the mechanism; multi-tenant deployer-facing oversight UI is Stronghold's | docs/adr/ADR-068-unified-authorization-and-elevation.md | not_applicable |
| **Art. 15** | Accuracy / robustness / cybersecurity | Hypothesis property tests (`formal/`) + mutation-testing gate + `bandit`/`ruff -S`/`semgrep` (per `security-scan` skill) | `formal/models/test_pii_filter.py`; `.github/workflows/mutation.yml` | partially_implemented |
| **Art. 17** | Quality management system | CI gate stack (lint + type + core tests + quality + security + mutation + registry + formal-conformance) | .github/workflows/quality.yml | partially_implemented |
| **Art. 26** | Deployer obligations | Per-scope audit access (soft scopes in core); hard per-tenant deployer obligations are Stronghold's | docs/adr/ADR-019-canonical-source-split.md | not_applicable |

## SOC 2 Type II (Trust Services Criteria)

The engine ships the structural prerequisites; a SOC 2 audit itself is a Stronghold-deployment
concern (this repo has no auditor engagement).

| TSC | Engine control | Evidence path | Status |
|---|---|---|---|
| Security (CC1–CC9) | Warden/Sentinel boundary scan (ADR-073) + ADR-068 authz ladder + secret redaction on log output (ADR-064, `security/log_redaction.py`) | packages/maistro-core/tests/security/test_log_redaction.py | partially_implemented |
| Availability (A1) | ADR-038 circuit breakers + healthchecks (`/health`, `/health/live`, `/health/ready`, `maistro_server/api/health.py`) ; evidence: `packages/maistro-server/tests/api/test_health.py`; `packages/maistro-core/tests/test_circuit_breaker.py` | packages/maistro-server/tests/api/test_health.py | partially_implemented |
| Processing Integrity (PI1) | Boundary/behavioral contracts (ADR-032), enforced by the `@pytest.mark.contract` suites in CI ; evidence: `packages/maistro-core/tests/builders/test_structural_gate.py` | packages/maistro-core/tests/builders/test_structural_gate.py | partially_implemented |
| Confidentiality (C1) | Soft memory scopes (core) + secret redaction on log output (ADR-064) + PII tiers (ADR-055); hard tenant confidentiality is Stronghold's | packages/maistro-core/tests/observability/test_tiers.py | partially_implemented |
| Privacy (P1–P8) | Sentinel PII filter (`security/sentinel/pii_filter.py`) + ADR-055 sensitivity tiers (`normal`/`sensitive`/`secret`) ; evidence: `formal/models/test_pii_filter.py`; `packages/maistro-core/tests/observability/test_tiers.py` | formal/models/test_pii_filter.py | partially_implemented |

## How this document is maintained

- This document is the human-readable mapping of the engine's control claims. The machine-readable
  schema and evidence records in `docs/compliance/claims.json` are the validation authority for the
  detailed tables' evidence; `quality/compliance-registry.json` (see Maintenance) remains the
  separate release-gating control registry. The scope is the engine only — Stronghold maintains its
  own COMPLIANCE.md for tenancy/IdP/deployer
  obligations, cross-referencing back here for the substrate it inherits.
- Run `uv run python scripts/check_compliance.py` locally after changing a row or cited artifact.
  The validator requires exact row/registry coverage, checks repository artifact digests, anchors
  immutable-execution receipts to commits that exist in this repository's git history, and refuses
  stale, disabled, manual-only, never-run, missing, or failing evidence for an `implemented` claim.
  It is intentionally not a required CI check in this child issue.
- Every `tests/...` or `formal/...` path cited above is represented by a typed evidence record.
  Repository-artifact evidence proves that the implementation/test source exists, not that a test
  executed. An `implemented` row additionally requires a current automated immutable execution
  receipt; the rows currently marked `partially_implemented` do not have that execution evidence
  in this repository snapshot. A PR that removes or renames a cited artifact must update the
  registry and the corresponding row in the same PR.
- Gap markers (`gap-test`, `gap-impl`, `gap-spec`) are expected, not embarrassing. They are the
  point of the document: a reader should be able to tell exactly what is proven, what is built but
  unproven, and what is only planned.
- Updates to this document accompany the relevant code/test PR, not a separate doc-only PR, except
  for the initial authoring pass (this one).

## Known deferrals to Stronghold (ADR-019)

Per ADR-019 (canonical source split) and ADR-068 §A (scope vs tenancy), the following classes of
control are **structurally out of scope for the engine** and are Stronghold's to implement and
attest:

- Hard `tenant` isolation (one tenant per user, full segmentation) — the engine only carries the
  soft scope axes `global → org → team → user → agent → session`.
- IdP integration (Keycloak / Entra ID / Auth0 / Okta) — the engine ships JWT/composite/static-key
  auth protocols; a specific IdP binding is a product concern.
- Deployer-facing transparency notices and per-tenant incident reporting (EU AI Act Art. 26).
- SOC 2 Type II audit engagement and evidence catalog assembly.

An evidence record identifies its control ID and exactly repeats its executable references. Historical green source records may use direct immutable Actions artifact URLs, or commit-bound workflow locators (`blob/<digest>/.github/workflows/...`) resolved to successful runs and deterministic artifact names. Direct records carry SHA-256; locators obtain it from GitHub. All green evidence requires an executed-test attestation, not just a generic green job. API failures, expired/deleted artifacts, and missing provenance fail closed; regenerate evidence before release if the 90-day Actions retention has elapsed. Automation verifies factual technical evidence only; owner review, downstream compliance interpretation, and legal sufficiency remain human responsibilities.
