---
id: ADR-039
title: External Library Adoption Policy
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-030
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-039: External Library Adoption Policy

## Context

Supply-chain attacks on Python packages have escalated through 2024–2026:

- Maintainer account compromises (PyPI token leaks, OAuth hijack)
- Long-running malicious infiltration (xz-utils class)
- Typosquatting and dependency confusion
- Release-artifact tampering after CI breach
- Stale-package adoption with malware injection
- Transitive deps that weren't audited

Stronghold's posture is security-first: every external import increases attack surface and audit obligation. The other three products tolerate more pragmatism but still need defensible decisions about what gets adopted. This ADR codifies the per-repo policy and the layered controls that make the policy enforceable.

It also establishes `INSPIRATIONS.md` as the append-only ledger for pattern references and convergent development — separate from `pyproject.toml` LICENSE attribution.

## Decision

### 1. Per-repo policy

| Repo | Policy |
|---|---|
| `agent-stronghold/stronghold` | **Anti-imports.** New external imports require ADR-level justification ("can't do it better, cheaper, faster, or more securely than building"). Service-boundary integrations (MCP, HTTP, queue) are explicitly OK and preferred. Existing deps grandfathered. |
| `BlakeMatthews-dev/Project_mAIstro` | **Pragmatic.** Import when it's better/cheaper/faster/more-secure than building. Maintainer-signal gate (§3) applies. |
| `BlakeMatthews-dev/AgentTuring` | **Pragmatic.** Same as `Project_mAIstro`. |
| `BlakeMatthews-dev/maistro-engine` | **Substrate constraint.** New imports must satisfy stronghold's bar (because engine deps cascade into stronghold). Existing deps grandfathered. |

### 2. The import / service-boundary distinction

`import x` ≠ `mcp.call_tool("x", …)`. They are categorically different attack surfaces:

| Mode | Trust boundary | Compromise blast radius |
|---|---|---|
| Python `import` | Process-internal | Full process: every secret, every tool, every memory access |
| Service call (MCP / HTTP / queue) | Network / protocol | The service's process only; not the calling agent |

The service-boundary preference is the same posture stronghold takes with LLMs (LiteLLM gateway = same pattern). Anthropic's code never runs in stronghold; stronghold uses Claude. The same logic applies to argus, Open Interpreter, fal-mcp-server, CLI-Anything-generated harnesses, and every other external tool we adopt.

### 3. Maintainer-signal gate

Before adopting any external library (import or service-boundary), evaluate:

| Signal | Pass criteria |
|---|---|
| Organizational backing | Real org / multi-contrib team — not solo |
| Activity | Release within last 12 months; recent commit activity |
| License compatibility | OSI-approved + compatible with the consuming repo's license (Apache 2.0 for stronghold + engine) |
| Open-issue health | Not abandoned (e.g., archived, hundreds of stale issues with no maintainer response) |
| Test coverage | Tests exist; CI runs |
| Transitive deps | Reviewed; no known-bad indirect deps |

Solo-maintained projects can be **pattern references** (§5) but should not be runtime dependencies under this policy. Exceptions require ADR-level justification per §1.

### 4. Layered controls

Beyond import policy:

| Control | Purpose | Status |
|---|---|---|
| `uv lock` / `--require-hashes` | Defends against malicious package updates mid-flight | Verify in CI |
| SBOM generation per release (CycloneDX or SPDX) | Vulnerable-transitive detection | `gap-impl` (see `[engine-NNN]`) |
| Sigstore / cosign signed release artifacts | Defends against artifact tampering | `gap-impl` |
| Maintainer-signal gate (§3) | Filters at adoption time | This ADR |
| Vendoring critical security paths | Audit-once, no surprise updates | Per-case decision |
| Dependency Review on PR (Dependabot/Renovate) | Surfaces transitive changes pre-merge | Verify in CI |
| Weekly OpenSSF Scorecard scan | Automated maintenance signals | `gap-impl` |

### 5. INSPIRATIONS.md per repo

Append-only ledger of external work we've drawn from, intentionally or convergently. Three sections:

- **Direct influences** — work whose patterns explicitly informed our design
- **Convergent / parallel development** — work that arrived at similar conclusions independently
- **Pattern references** — read but no code copied

The ledger has no completeness obligation. **"The absence of an entry is not a claim of originality."** Append on discovery; don't audit retrospectively.

For *dependencies* (in `pyproject.toml` etc.), the standard `LICENSE` / `NOTICE` attribution is sufficient. INSPIRATIONS is for *patterns* and *concepts*, not for legally-required dependency attribution.

### 6. Application to the catalog discussions

Decisions reached in the May 2026 catalog review under this policy:

| Item | Disposition |
|---|---|
| `compemperor/engram` (drift detection) | Pattern reference; one-line backlog item for memory drift detection in engine |
| `coleam00/Archon` (catalog patterns) | Pattern reference only; ACL v1.2 license incompatible with Apache 2.0 commercial use |
| `Khamel83/oneshot` ecosystem | Pattern references (lane fallback chains, janitor signal files, cross-machine secrets, doctor command) |
| `Khamel83/argus` | Service-boundary integration (MCP) for all three products |
| `HKUDS/CLI-Anything` | Service-boundary integration (subprocess harnesses) for all repos; not pip-installed into stronghold |
| FastAPI Azure Auth, AuthX | Possible imports for `Project_mAIstro` only (not stronghold) |
| FastAPI Casbin Auth, FastAPI Guard | Pattern references; stronghold builds equivalents in Warden + bare PyCasbin |
| Promptfoo, Open Interpreter | Service-boundary integration (CI tool / sandboxed exec) |
| AutoGen, MetaGPT, Camel AI, Crew AI, MemGPT, Llama Index, Pezzo, Lunary | Pattern references in INSPIRATIONS.md |
| ~150 others | Failed maintainer-signal gate or out of scope |

## Consequences

- Stronghold's adoption decisions become auditable: every external lib has either an ADR exception or a service-boundary justification.
- The engine ADR template gains an "Inspirations" section authors fill out at draft time when applicable.
- `stronghold/COMPLIANCE.md` AT-10 (Supply chain) anchors to this ADR.
- The catalog discussions settle into one of: dependency, service-boundary integration, pattern reference (INSPIRATIONS.md), or rejection.
- Future "should we adopt X?" debates have a deterministic answer: run X through §1 + §3, decide.

## Out of scope

- SBOM tooling choice (CycloneDX vs SPDX) — separate engine ADR.
- Sigstore / cosign integration — separate engine ADR.
- Specific OSS license review beyond compatibility check — case-by-case in adopting ADRs.
- The OWASP Agentic Top 10 mapping itself — lives in `stronghold/COMPLIANCE.md`; this ADR is a control that mapping cites.
