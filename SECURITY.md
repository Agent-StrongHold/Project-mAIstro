# Maistro Engine — Security Model

**Scope:** `maistro-engine` (the homelab-and-library monorepo: `maistro-core`, `maistro-canvas`,
`maistro-server`, `maistro-turing`, `maistro-evolve`, `hive-conductor`). Multi-tenancy, hard tenant
isolation, and IdP integration are out of scope here — they are Stronghold's, the downstream
product that imports this engine and adds them (ADR-019).

---

## Threat model

The full threat model — assets, ranked adversaries, trust boundaries, and defense posture — lives
in **[ADR-072](docs/adr/ADR-072-threat-model.md)**. It is not duplicated here; the summary:

- **Primary adversary: malicious third-party code** (a bad skill, a compromised MCP server, a
  poisoned dependency). Defense is structural — signing, microVM isolation, trust tiers — never
  "ask the model to behave."
- Secondary adversaries, ranked: prompt injection, local device/LAN compromise, a compromised
  federation peer, an over-privileged or drifting agent.
- Trust boundaries are scanned by Warden (both directions at the MCP boundary) and adjudicated by
  Sentinel (every tool call) — specified in **[ADR-073](docs/adr/ADR-073-warden-sentinel.md)**.
- Accepted risks / explicitly out of scope for the engine: physical coercion of the operator,
  nation-state targeted attacks, hypervisor-beneath-the-microVM compromise, and multi-tenant
  isolation (Stronghold's threat model, not this repo's).

---

## Defense-in-depth layers

| Layer | Mechanism | Engine module |
|---|---|---|
| **1. Gate** | Untrusted-input entry point into the Conduit pipeline | `maistro/conduit.py` |
| **2. Warden** | Trust-boundary scanner: fast-tier heuristics (regex/pattern/anomaly, free) escalate only ambiguous input to an LLM judge (risk `0..1`). Scans user input, tool results, and — at the MCP boundary — both ingress and egress | `maistro/security/warden/detector.py`, `heuristics.py`, `semantic.py`, `llm_classifier.py`, `sanitizer.py`, `patterns.py` |
| **3. Sentinel (AuthZ / elevation)** | Policy decision + enforcement point (PDP/PEP) at the tool-call boundary. Evaluates CLASSIFY → AUTHORIZE → BUDGET → GATE (ADR-068) in order, stopping at first deny | `maistro/security/sentinel/policy.py`, `validator.py`, `elevation.py`, `approver_graph.py`, `rlphd.py` |
| **4. Skill / tool trust tiers** | Skill body size cap + `security_scan()` (exec/eval/subprocess/credential/injection patterns) at import; dangerous-command and dangerous-tool-name detection at call time. **Reversibility classification does NOT currently gate anything** — `ReversibilityRegistry` is never constructed and `Sentinel.resolve_tier` never consults it (#346). Skill scanning runs on the CRUD write paths and `POST /v1/skills/scan` (#347), but those are content-only: skills created that way do not pass `import_pipeline.import_skill`, so no signing, T3 sandboxing, or rescan-on-use binding applies to them | `maistro/skills/parser.py`, `skills/import_pipeline.py`, `security/dangerous_tools.py`, `tools/reversibility_registry.py` |
| **5. Resource protection** | Quota tracking, per-key rate limiting, circuit breakers/retry/fallback, secret redaction on log output, result-size truncation (see inventory below) | `maistro/quota/tracker.py`, `security/rate_limiter.py`, `resilience/`, `security/redact.py` + `security/log_redaction.py`, `security/sentinel/token_optimizer.py` |
| **6. Sandbox isolation** | Untrusted agent/tool code MUST run behind a hardware-VM boundary (microVM), not a shared-kernel container; the Docker-socket-mounting sandbox is deprecated for untrusted workloads (ADR-093) | `maistro/tools/sandbox/`, `maistro/sandbox/protocol.py` |

This is the engine's version of Stronghold's Gate → Warden → Identity → Skill → Resource
five-layer model, with sandbox isolation (ADR-093) called out as its own layer because it is a
harder guarantee (hypervisor boundary) than the container/RBAC layers above it.

### Account credential storage

Conductor accounts are hashed with **Argon2id** (`maistro/security/passwords.py`), OWASP
interactive-login parameters: 64 MiB memory, 3 iterations, parallelism 4, 32-byte hash,
16-byte salt. bcrypt hashes still **verify** so pre-existing accounts keep working, and a
successful login rewrites any non-current hash to Argon2id — so the bcrypt population drains
by use rather than needing a migration. A stored hash that cannot be decoded denies the login;
it never admits, and never overwrites the stored value.

This row is evidence-backed rather than asserted: `packages/maistro-core/tests/security/`
`test_passwords.py` covers hash/verify/rehash and every malformed-input branch, and
`packages/hive-conductor/backend/tests/test_auth_password_storage.py` proves the product
claims on the real HTTP path — registration stores Argon2id, a bcrypt row is upgraded on its
owner's first login without changing the password, a failed login leaves the hash untouched,
and four shapes of corrupt hash return 401.

---

## Resource-limits inventory

Real numeric caps found in the engine (grepped, not asserted from memory — each cites its
`file:constant`):

| Limit | Value | File:constant | Purpose |
|---|---|---|---|
| Warden regex scan window | 50 KiB, 2 KiB overlap | `security/warden/detector.py:81-82` (`window_size = 50 * 1024`, `overlap = 2 * 1024`) | ReDoS / pathological-input protection while still catching cross-chunk patterns |
| Warden pattern-match timeout | 0.5 s | `security/warden/detector.py:27` (`_PATTERN_TIMEOUT_S`) | Bounds a single regex pass |
| Warden heuristic instruction-density threshold | 0.15 | `security/warden/heuristics.py:32` (`INSTRUCTION_DENSITY_THRESHOLD`) | Flags imperative-verb-dense (likely-injected) content |
| Skill body size | 50,000 chars | `skills/parser.py:25` (`MAX_SKILL_BODY_LENGTH`) | Context-window-stuffing protection, enforced at both parse (`parser.py:116`) and import (`import_pipeline.py:210`) |
| Learning store cap | 10,000 entries | `memory/learnings/store.py:15` (`MAX_LEARNINGS`) | OOM protection (FIFO-style bound on the in-memory store) |
| `find_relevant` result cap | 10 results (default) | `memory/learnings/store.py:66` (`max_results: int = 10`) | Context-overflow protection |
| Learning `list_all` page cap | 200 entries (default) | `memory/learnings/store.py:161` (`limit: int = 200`) | Bounds a single audit/listing call |
| Tool-result truncation | 4,000 chars | `security/sentinel/token_optimizer.py:7` (`MAX_RESULT_LENGTH`) | Token-budget / context-stuffing protection on oversized tool results |
| Task-spec description length | 50,000 chars | `constants.py:27` (`PERMISSION_MAX_INPUT`), enforced in `security/trust_boundary.py` (`TaskSpec.validate_spec`) | Prompt-stuffing prevention on cross-trust-boundary task specs |
| Permission grant TTL | 3,600 s | `constants.py:24` (`PERMISSION_TTL`) | Time-boxes a `PermissionGrant` |
| Self-elevation grant TTL | 300 s | `security/sentinel/elevation.py:103` (`DEFAULT_SELF_ELEVATION_TTL_SECONDS`) | Bounds a sudo-style re-auth grant (ADR-068 §D). **Not yet in force:** no surface issues grants, so nothing is bounded by this today (#346) |
| Scoped-2FA grant TTL | 120 s | `security/sentinel/elevation.py:104` (`DEFAULT_SCOPED_2FA_TTL_SECONDS`) | Bounds an agent's owner-signed elevation request. **Not yet in force** — same reason |
| Rate limiter window / burst window | 60 s / 1 s | `security/rate_limiter.py:30-31` (`self._window`, `self._burst_window`) | Sliding-window + burst limiting per key |
| Rate limiter key eviction age | 300 s | `security/rate_limiter.py:16` (`_KEY_EVICTION_AGE_S`) | Bounds in-memory key table growth |
| Circuit breaker defaults | N=5 failures / W=60s window / T=30s cooldown | ADR-038 §2 (implemented in `resilience/`) | Per-upstream-dependency failure isolation |
| Secret-redaction pattern catalogue | 30+ patterns, single-pass span merge, plus a >4.0 bits/char entropy fallback for unknown key formats | `security/redact.py` (ADR-064), installed by `security/log_redaction.py` | Scrubs API keys, JWTs, private-key blocks, connection strings, etc. **Operative on both log pipelines** — every stdlib handler (Conductor + uvicorn) and the structlog processor chain (`maistro-server`), covering `%`-args and exception tracebacks. `/health` reports `log_redaction_active`. It does **not** cover anything that bypasses logging — `print()`, an HTTP response body, or a value written straight to disk |

### Gaps against Stronghold's inventory

Stronghold's `SECURITY.md` carries several caps the engine does not (yet) have an equivalent for:

| Stronghold had | Engine has | Status |
|---|---|---|
| Tool-argument size limit (100 KB, JSON-bomb protection) | No dedicated tool-arg size cap found in `security/sentinel/validator.py` or `tools/` | `gap-impl` |
| SSRF blocklist (private networks, cloud metadata endpoints, loopback) for outbound tool/skill HTTP calls | Only a **filesystem** path blocklist exists (`security/patterns.py:BLOCKED_HOST_PATHS` — `/etc`, `/proc`, `/sys`, `/dev`, `/root`, `/boot`, Docker socket paths); no URL/host-based SSRF blocklist was found in `tools/browser/client.py`, `skills/marketplace.py`, or `skills/import_pipeline.py`, all of which make outbound HTTP calls | `gap-impl` — real risk: a skill or connector fetching an attacker-controlled URL can reach `169.254.169.254` or a LAN-internal service today |
| `hmac.compare_digest`-based constant-time comparison for API keys | Present: `security/secret_equal.py` | ✅ (engine has this) |
| PostgreSQL persistence with org-scoped queries by default | InMemory stores are the default; PostgreSQL implementations exist (`persistence/`) but require explicit configuration | Matches engine's own known limitation below, not a regression |

---

## OWASP Top 10 for LLM Applications (2025) — short mapping

| ID | Threat | Engine mitigation |
|---|---|---|
| LLM01 | Prompt Injection | Warden fast-tier heuristics + LLM-judge escalation on ambiguity (`security/warden/`) |
| LLM02 | Sensitive Information Disclosure | Sentinel PII filter (`security/sentinel/pii_filter.py`) + secret redaction on both log pipelines (`security/redact.py` installed by `security/log_redaction.py`, ADR-064). The PII filter reaches only callers of the Sentinel post-call pipeline, which the Conductor chat path does not traverse (#350) |
| LLM03 | Supply Chain (skills / MCP / dependencies) | Skill content scan on the CRUD write paths (`skills/parser.py::security_scan`, #347) + microVM isolation for untrusted code (ADR-093). **Two caveats:** `import_pipeline.import_skill`'s full gate has no production caller, and **signed code-registry entries (`code_registry/verify.py`, ADR-069) are not operative** — `CodeRegistry.register()` is never called, so nothing is signature-checked at load (#346) |
| LLM04 | Data / Model Poisoning | Warden scan on tool results before they re-enter context; learning promotion gate (`memory/learnings/promoter.py`) |
| LLM05 | Improper Output Handling | Sentinel post-call pipeline: Warden scan + PII filter + token-result truncation (`security/sentinel/token_optimizer.py`) |
| LLM06 | Excessive Agency | ADR-068 tier ladder (open → role-auto → self-elevation → delegated-approval → admin-elevation → blocked); agents hold a strict **subset** of their owning human's authority, never more |
| LLM07 | System Prompt Leakage | Warden pattern set includes system-prompt-extraction detection (`security/warden/patterns.py`) |
| LLM08 | Embedding Weaknesses | Learning embeddings module (`memory/learnings/embeddings.py`); no cross-tenant cache concern in-engine (soft scopes only) |
| LLM09 | Misinformation | Classifier three-phase confidence scoring (keyword → LLM fallback → complexity) informs when to escalate rather than guess |
| LLM10 | Unbounded Consumption | Size caps throughout (see resource-limits inventory above) + quota tracker + rate limiter |

---

## Known Limitations (honest assessment)

1. **No SSRF blocklist for outbound HTTP.** Skills, connectors, and the browser tool all make
   outbound HTTP calls (`skills/marketplace.py`, `skills/import_pipeline.py`,
   `tools/browser/client.py`). Only a filesystem-path blocklist exists
   (`security/patterns.py:BLOCKED_HOST_PATHS`); nothing blocks a request to
   `169.254.169.254` (cloud metadata) or a LAN-internal address. This is the single largest gap
   relative to Stronghold's inventory.
2. **No dedicated tool-argument size cap.** Sentinel validates schema and permissions
   (`security/sentinel/validator.py`) but a JSON-bomb-sized tool-call argument is not rejected by
   a specific byte-size gate the way skill bodies (50 KB) and tool results (4,000 chars) are.
3. **Sentinel decision signing is unimplemented.** ADR-073 specifies every Sentinel decision as a
   signed VC; the current `InMemoryAuditLog` (`security/sentinel/audit.py`) records decisions but
   does not sign them. A compromised process with write access to the audit store could forge
   history.
4. **InMemory stores are the default.** Learning store, audit log, quota tracker, and session
   store all default to in-memory implementations; data is lost on restart. PostgreSQL
   implementations exist under `persistence/` but require explicit `database_url` configuration —
   nothing forces the switch.
5. **PII filter is pattern-based.** `security/sentinel/pii_filter.py` is regex-driven;
   homoglyph/encoding-based evasion is only partially mitigated (Warden applies NFKD normalization
   before scanning, but the PII filter itself does not). `security/redact.py` additionally carries a
   Shannon-entropy fallback (`_looks_like_secret`, >4.0 bits/char with a mixed charset) that catches
   unknown key formats an earlier revision of this section wrongly said it lacked; that fallback
   does not extend to the PII filter. **Redaction covers the log pipelines only** — a secret placed
   in an HTTP response body or written directly to a file is not scrubbed.
6. **Warden's LLM-judge tier is fail-open by design intent, not yet verified in code.** ADR-073
   specifies the escalation tier scores risk on ambiguity only; the fail-open behavior on judge
   error (matching Stronghold's documented L3 fail-open pattern) was not independently confirmed
   against `security/warden/llm_classifier.py` during this audit — flagged for follow-up, not
   asserted either way.
7. **No content-safety / toxicity filtering.** Warden's scope is threat detection (injection,
   exfiltration, dangerous commands), not hate-speech or general content moderation.
8. **Sandbox microVM backend is not yet the default everywhere.** ADR-093 mandates a microVM
   (Firecracker/Kata/Hyperlight) or, at minimum, gVisor for unattended execution, with a Tier-3
   (hardened container) floor only for interactive/supervised sessions. CI today exercises the
   sandbox selector and a fake backend (`tests/sandbox/backends/test_fake.py`); a real hardware-VM
   backend passing the SPEC-190 conformance/escape suite was not found under `formal/` or
   `packages/maistro-core/tests/` at the time of writing.
9. **Circuit-breaker and quota defaults are engine-wide, not per-deployment-tuned.** ADR-038's
   `N=5, W=60s, T=30s` and the learning-store/rate-limiter constants above are code defaults; a
   given deployment that needs stricter limits must override them explicitly — there is no
   config-driven ratchet enforcing a floor.
10. **This document itself is new.** It was authored as part of a Wave-1 governance pass and has
    not yet been exercised by an incident or a red-team engagement against this specific text —
    treat every "✅" above as "code review confirms this exists and is tested," not "this has
    survived an attack."

---

## Reporting a vulnerability

If you discover a security vulnerability in `maistro-engine`, please report it privately rather
than opening a public issue.

- Use GitHub's private vulnerability reporting: open a draft security advisory under this
  repository's **Security** tab (`Security → Advisories → Report a vulnerability`).
- Include a description of the issue, affected component/module path, reproduction steps, and
  potential impact.
- Do not include real credentials, tokens, or production data in the report — describe the class
  of secret rather than pasting a live one.

We follow coordinated disclosure: acknowledge receipt promptly, investigate, and publish an
advisory once a fix is available or a mitigation is documented. This project has no dedicated
security team or SLA at this time — response times are best-effort.

## Known scanning carve-out: `cage/` and `eval/`

`packages/hive-conductor/{cage,eval}` are excluded from the semgrep sweep
(`security.yml`) **and** frozen by `cage-guard.yml`, which fails any PR
touching them. Those two facts together mean the code that executes
model-generated output is currently neither scanned nor modifiable through the
normal PR flow — a deliberate freeze, recorded here so it reads as a decision
rather than an oversight.

How a legitimate change lands today: a maintainer disables the `cage-guard`
requirement for the specific PR in the GitHub UI (branch-protection admin),
merges, and re-enables it. The right end state is a tailored semgrep ruleset
for these paths (the generic rules false-positive on intentional `exec`) plus
a documented override label — tracked as follow-up work, not claimed as done.
