# Maistro Engine — Compliance Mappings

**Scope:** `maistro-engine` (the monorepo: `maistro-core`, `maistro-canvas`, `maistro-server`,
`maistro-turing`, `maistro-evolve`, `hive-conductor`). This document maps the **engine's** controls
only. Multi-tenancy, IdP integration, and per-tenant policy are Stronghold's concern (ADR-019); rows
that depend on tenancy are marked **deferred to importing product (Stronghold) per ADR-019** rather
than scored against the engine.

This document maps engine controls to:

- **OWASP Agentic Top 10** (2026 baseline for AI-agentic systems)
- **NIST AI Risk Management Framework** (Govern, Map, Measure, Manage)
- **EU AI Act** (Articles 9–15, 17, 26 — high-risk system requirements)
- **SOC 2 Type II** (Trust Services Criteria)

Each row cites the module(s)/ADR(s) that implement the control **and** the test path that proves
it. A line without a resolvable test path is `gap-test`. A line without an implementation is
`gap-impl`. A line with no plan at all is `gap-spec`. Every path below was verified against the
repo at the time of writing (`ls`/`grep`, not memory) — if a path stops resolving, the marker must
flip to `gap-test`/`gap-impl` in the same PR that breaks it.

## Legend

| Status | Meaning |
|---|---|
| `implemented` | Technical control is implemented with current automated evidence |
| `partially_implemented` | Some implementation or execution seams remain incomplete |
| `documented` | The control is specified or mapped, but not asserted as an implementation |
| `planned` | The control is planned or specified but not implemented |
| `not_applicable` | Deferred to the importing product (Stronghold, per ADR-019) |
| `unverified` | No current evidence supports a stronger state |

---

## OWASP Agentic Top 10

| ID | Risk | Engine control | Test path | Status |
|---|---|---|---|---|
| **AT-01** | Memory poisoning | Warden boundary scan (`security/warden/detector.py`) + episodic memory decay/weight floors (ADR-013 scopes) + learning promotion gate | `packages/maistro-core/tests/security/warden/test_detector.py`; `packages/maistro-core/tests/memory/episodic/test_decay.py`; `packages/maistro-core/tests/memory/learnings/test_promoter_gate.py` | implemented |
| **AT-02** | Tool misuse | Sentinel PDP/PEP at the tool-call boundary (ADR-073) — `security/sentinel/policy.py`, `security/sentinel/validator.py` — + dangerous-command/tool detection (`security/dangerous_tools.py`). **Reversibility classification (`tools/reversibility_registry.py`, ADR-050) is NOT operative** — `ReversibilityRegistry` is never constructed; `Sentinel.resolve_tier` branches on a caller-supplied `reversibility` string defaulting to `"reversible"` and never consults the registry (#346) | `packages/maistro-core/tests/security/test_sentinel_policy.py`; `packages/maistro-core/tests/security/test_sentinel_validator.py`; `formal/models/test_dangerous_tools.py`; `formal/models/test_sentinel_policy.py`; `formal/models/test_sentinel_validator.py` | partially_implemented |
| **AT-03** | Privilege compromise | ADR-068 tier ladder (open → role/team-auto → self-elevation → delegated-approval → admin-elevation → blocked), `security/sentinel/elevation.py`, admin/user1 privilege separation (`privilege.py`, SPEC-012) | `packages/maistro-core/tests/security/test_authz_tier_ladder.py`; `packages/maistro-core/tests/security/test_elevation_grants.py`; `packages/maistro-core/tests/privilege/test_privilege.py` | implemented |
| **AT-04** | Resource overload | Quota tracker (`quota/tracker.py`) + per-key rate limiter (`security/rate_limiter.py`) + circuit breakers / retry / fallback (ADR-038, `resilience/`) | `packages/maistro-core/tests/quota/test_tracker.py`; `packages/maistro-core/tests/security/test_rate_limiter.py`; `packages/maistro-core/tests/test_circuit_breaker.py`; `packages/maistro-core/tests/resilience/test_retry_policy.py` | implemented |
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

## NIST AI Risk Management Framework (AI RMF)

Reference: NIST AI 100-1, NIST AI 100-2 (Generative AI Profile).

### Govern

| Function | Engine control | Status |
|---|---|---|
| GOVERN-1 (Policies, processes, structures) | Sentinel declarative policy layer, DB-backed + RBAC-editable + YAML/JSON export (ADR-073) | partially_implemented |
| GOVERN-2 (Accountability) | Sentinel decision audit (`security/sentinel/audit.py`) + ADR-037 event log | partially_implemented |
| GOVERN-3 (Workforce / culture) | `CLAUDE.md`, ADR ladder (`docs/adr/`) | documented |
| GOVERN-4 (Engagement / oversight) | ADR-068 elevation ladder + approval gate (`tools/approval/gate.py`) | partially_implemented |
| GOVERN-5 (Lifecycle) | Front-matter status lifecycle (ADR-031, enforced by `maistro-registry` CI, `registry.yml`) | implemented |

### Map

| Function | Engine control | Status |
|---|---|---|
| MAP-1 (Context) | ADR-072 threat model (assets, adversaries, trust boundaries) | documented |
| MAP-2 (Categorization) | OWASP Agentic Top 10 mapping (this document) | documented |
| MAP-3 (Capabilities) | `maistro.capabilities` slot/provider registry (SPEC-184) | implemented |
| MAP-4 (Risk impact) | ADR-072 asset/adversary tables; this document | documented |
| MAP-5 (Risk priority) | ADR-072 "Adversaries (ranked)" list | documented |

### Measure

| Function | Engine control | Status |
|---|---|---|
| MEASURE-1 (Identification) | Builders pipeline (spec → tests → code → review, `builders/`) + structural-awareness gate ; evidence: `packages/maistro-core/tests/builders/test_structural_gate.py` | partially_implemented |
| MEASURE-2 (Tracking) | ADR-037 observability (traces/metrics/logs/events) + ADR-055 replay ; evidence: `packages/maistro-core/tests/observability/test_tracing.py`; `packages/maistro-core/tests/observability/test_replay.py` | implemented |
| MEASURE-3 (Effectiveness) | Mutation testing gate (`mutation.yml` CI workflow) | implemented |
| MEASURE-4 (Feedback) | Learning promotion pipeline (`memory/learnings/promoter.py`) ; evidence: `packages/maistro-core/tests/memory/learnings/test_promoter.py` | implemented |

### Manage

| Function | Engine control | Status |
|---|---|---|
| MANAGE-1 (Risk treatment) | Warden/Sentinel boundary scanning (ADR-073) + ADR-038 circuit breakers | implemented |
| MANAGE-2 (Allocation) | Quota tracker (`quota/tracker.py`) + router scarcity-based cost ; evidence: `packages/maistro-core/tests/quota/test_tracker.py` | implemented |
| MANAGE-3 (Pre-deployment) | CI gate stack (`ci.yml`, `quality.yml`, `security.yml`, `formal-conformance.yml`, `mutation.yml`, `cage-guard.yml`) | implemented |
| MANAGE-4 (Documentation / response) | This document + `SECURITY.md` + Sentinel audit log | planned |

## EU AI Act (High-risk systems)

Reference: Regulation (EU) 2024/1689, Articles 9–15, 17, 26.

| Article | Requirement | Engine control | Evidence path | Status |
|---|---|---|---|---|
| **Art. 9** | Risk-management system | ADR-072 threat model + this COMPLIANCE.md | docs/adr/ADR-072-threat-model.md | documented |
| **Art. 10** | Data governance | Memory scope axes (global→org→team→user→agent→session, ADR-019 Decision 7) + Sentinel PII filter (`security/sentinel/pii_filter.py`) + secret redaction on both log pipelines (`security/redact.py` installed by `security/log_redaction.py`, ADR-064) | `formal/models/test_memory_scopes.py`; `formal/models/test_pii_filter.py`; `packages/maistro-core/tests/security/test_redact.py`; `packages/maistro-core/tests/security/test_log_redaction.py` | partially_implemented |
| **Art. 11** | Technical documentation | ADR ladder (`docs/adr/`, 100+ ADRs) + `CLAUDE.md` | CLAUDE.md | documented |
| **Art. 12** | Record-keeping | Sentinel decision audit + durable event log (`events/`) | packages/maistro-core/tests/events/test_durable_log.py | partially_implemented |
| **Art. 13** | Transparency to users | Warden flag-and-warn responses (`security/warden/flag_response.py`) surface why content was blocked/flagged | `formal/models/test_flag_response.py` | implemented |
| **Art. 14** | Human oversight | ADR-068 elevation ladder (self-elevation / scoped-2FA / delegated / admin) is the mechanism; multi-tenant deployer-facing oversight UI is Stronghold's | docs/adr/ADR-068-unified-authorization-and-elevation.md | not_applicable |
| **Art. 15** | Accuracy / robustness / cybersecurity | Hypothesis property tests (`formal/`) + mutation-testing gate + `bandit`/`ruff -S`/`semgrep` (per `security-scan` skill) | `formal/models/test_pii_filter.py`; `.github/workflows/mutation.yml` | implemented |
| **Art. 17** | Quality management system | CI gate stack (lint + type + core tests + quality + security + mutation + registry + formal-conformance) | .github/workflows/quality.yml | implemented |
| **Art. 26** | Deployer obligations | Per-scope audit access (soft scopes in core); hard per-tenant deployer obligations are Stronghold's | docs/adr/ADR-019-canonical-source-split.md | not_applicable |

## SOC 2 Type II (Trust Services Criteria)

The engine ships the structural prerequisites; a SOC 2 audit itself is a Stronghold-deployment
concern (this repo has no auditor engagement).

| TSC | Engine control | Evidence path | Status |
|---|---|---|---|
| Security (CC1–CC9) | Warden/Sentinel boundary scan (ADR-073) + ADR-068 authz ladder + secret redaction on log output (ADR-064, `security/log_redaction.py`) | packages/maistro-core/tests/security/test_log_redaction.py | partially_implemented |
| Availability (A1) | ADR-038 circuit breakers + healthchecks (`/health`, `/health/live`, `/health/ready`, `maistro_server/api/health.py`) ; evidence: `packages/maistro-server/tests/api/test_health.py`; `packages/maistro-core/tests/test_circuit_breaker.py` | packages/maistro-server/tests/api/test_health.py | implemented |
| Processing Integrity (PI1) | Boundary/behavioral contracts (ADR-032), enforced by the `@pytest.mark.contract` suites in CI ; evidence: `packages/maistro-core/tests/builders/test_structural_gate.py` | packages/maistro-core/tests/builders/test_structural_gate.py | partially_implemented |
| Confidentiality (C1) | Soft memory scopes (core) + secret redaction on log output (ADR-064) + PII tiers (ADR-055); hard tenant confidentiality is Stronghold's | packages/maistro-core/tests/observability/test_tiers.py | partially_implemented |
| Privacy (P1–P8) | Sentinel PII filter (`security/sentinel/pii_filter.py`) + ADR-055 sensitivity tiers (`normal`/`sensitive`/`secret`) ; evidence: `formal/models/test_pii_filter.py`; `packages/maistro-core/tests/observability/test_tiers.py` | formal/models/test_pii_filter.py | implemented |

## How this document is maintained

- This document is the human-readable mapping of the engine's control claims. The machine-readable
  schema and evidence records in `docs/compliance/claims.json` are the validation authority. The
  scope is the engine only — Stronghold maintains its own COMPLIANCE.md for tenancy/IdP/deployer
  obligations, cross-referencing back here for the substrate it inherits.
- Run `uv run python scripts/check_compliance.py` locally after changing a row or cited artifact.
  The validator requires exact row/registry coverage, checks repository artifact digests, and
  refuses stale, disabled, manual-only, never-run, missing, or failing evidence for an
  `implemented` claim. It is intentionally not a required CI check in this child issue.
- Every `tests/...` or `formal/...` path cited above is represented by a typed evidence record.
  A PR that removes or renames a cited artifact must update the registry and the corresponding
  row in the same PR.
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
