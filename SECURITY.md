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
| Warden pattern-match timeout | 0.5 s | `security/warden/detector.py:32` (`_PATTERN_TIMEOUT_S`) | Bounds a single regex pass |
| Warden heuristic instruction-density threshold | 0.15 | `security/warden/heuristics.py:34` (`INSTRUCTION_DENSITY_THRESHOLD`) | Flags imperative-verb-dense (likely-injected) content |
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

### Configurable limits and their enforced floors

Six of the caps above are deployment policy rather than code constants
(`SPEC-082226-2a10`, `security/resource_policy.py`). **The shipped default and the
enforced floor are the same number** — the value the engine has always shipped is
also the weakest one it will accept. Tightening is always allowed; crossing the
floor in the weakening direction fails `Settings` validation at startup, naming
the setting and the override that would permit it.

| Setting (env var) | Default = floor | Tighter means | Enforced by |
|---|---|---|---|
| `MAX_REQUEST_BODY_BYTES` | 1,048,576 | smaller | `PayloadSizeLimitMiddleware` |
| `MAX_WEBHOOK_BODY_BYTES` | 1,048,576 | smaller | webhook routes |
| `RATE_LIMIT_PER_MINUTE` | 60 | smaller | `security/rate_limiter.py` |
| `RATE_LIMIT_BURST` | 10 | smaller | `security/rate_limiter.py` |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | 5 | smaller | `agents/circuit_breaker.py` (LLM provider) |
| `CIRCUIT_BREAKER_RECOVERY_TIMEOUT_S` | 60.0 | **larger** | `agents/circuit_breaker.py` (LLM provider) |

Recovery timeout is the one that inverts: a shorter cooldown reopens the circuit
to a failing provider sooner, so *larger* is the safer direction.

`RATE_LIMIT_BURST=0` is the limiter's "no separate burst check" sentinel, not a
limit of zero — the burst window is skipped and the per-minute limit is the only
bound. A *nonzero* burst above the per-minute limit is capped by it for the same
reason: the limiter checks the minute window first and returns before the burst
window is consulted. The floor compares what the limiter enforces either way, so
`RATE_LIMIT_PER_MINUTE=2` is accepted with a burst of 0 or 50 (both admit two a
second, tighter than 10) while 6,000 with no burst throttle is refused.

Non-finite values are refused in every mode, override included. `nan` fails
every comparison, so it passed the floor checks and then disabled the control it
was set on — a circuit breaker with a `nan` recovery timeout opens and never
becomes half-open.

`ALLOW_UNSAFE_RESOURCE_OVERRIDES=true` is the only way to configure a value below
its floor, and it exists for development and deliberate unsafe deployments.
`DEBUG` does not grant it — weakening a security limit takes its own statement,
not a flag another subsystem might set for unrelated reasons. Non-positive values
are rejected in every mode, unsafe included.

`GET /health/ready` reports the effective values under
`effective_resource_policy`, including `unsafe_overrides_enabled`, so what a
process is actually enforcing can be read rather than inferred from the
environment it was supposed to have been given.

### Gaps against Stronghold's inventory

Stronghold's `SECURITY.md` carries several caps the engine does not (yet) have an equivalent for:

| Stronghold had | Engine has | Status |
|---|---|---|
| Tool-argument size limit (100 KB, JSON-bomb protection) | No dedicated tool-arg size cap found in `security/sentinel/validator.py` or `tools/` | `gap-impl` |
| SSRF blocklist (private networks, cloud metadata endpoints, loopback) for outbound tool/skill HTTP calls | **Present** — `security/ssrf.py` refuses any URL that is not http(s) with a resolvable host on the public internet, checking every address the host resolves to (private, loopback, link-local, reserved, multicast, unspecified) and refusing when the name cannot be resolved at all. Applied at `maistro.http`'s pooled transport (`security/outbound.py`, ADR-082326-5386), so every module that reaches the network through the shared pool is covered, including redirect hops. Configured endpoints — the LiteLLM/Ollama gateway, ntfy, a Home Assistant URL — are allowed by exact origin, seeded from settings. The **filesystem** path blocklist (`security/patterns.py:BLOCKED_HOST_PATHS`) is separate and unrelated | `partial` — covered at the seam, proxy mounts included; the rebinding window between the guard's lookup and the client's remains open |
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

1. **SSRF protection is applied at the shared-client transport, not at call sites.**
   `security/ssrf.py` refuses anything that is not http(s) with a resolvable host, and checks
   every address the host resolves to — which normalises the obfuscations (`2852039166`,
   `0x7f000001`, `127.1`, `[::ffff:169.254.169.254]`, `metadata.google.internal`) to the address
   they denote. A host that cannot be resolved is refused rather than allowed.

   It used to be a function each call site had to remember to call, and reached **3 of the 25**
   modules in `maistro-core` that issue an outbound request. It is now applied by
   `security/outbound.py` at the transport `maistro.http` hands to every pooled client
   (ADR-082326-5386), so a module is covered by routing through the shared pool rather than by
   remembering — and redirect hops are validated per hop, because httpx re-enters the transport
   for each one. `tasks/progress_webhook` and `integrations/ntfy` built private clients and were
   moved onto the pool so the seam actually reaches them.

   Configured destinations are allowed by exact origin (scheme, host, port), seeded from settings
   rather than a hand-maintained list, so the engine still reaches its own LiteLLM/Ollama
   gateway. An allowance names one endpoint; it does not widen to other ports on that host or to
   private addresses generally.

   Proxy egress is covered: httpx builds its own mounts from `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`
   and each of them is wrapped, so a deployment behind a proxy is both guarded and still able to
   reach its proxy.

   Two limits, stated rather than implied: the guard resolves the name and the HTTP client
   resolves it again when it connects, so a name that answers differently between those two
   lookups is not caught; and a transport that fabricates responses (`httpx.MockTransport`, which
   is how the test suite avoids the network) is not wrapped, because it opens no socket.
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
6. **Warden's configured LLM-judge tier fails closed on uncertainty.** When L3 is invoked, only an
   exact `safe` response clears the judge. Provider errors, timeouts, empty/malformed responses,
   and partial/prose classifications are projected onto the suspicious/non-clean path and carry an
   `llm_judge_inconclusive:*` reasoning trace so classifier failure is observable rather than
   silently treated as safe. A judge that cannot be consulted at all fails closed the same way
   (`llm_judge_inconclusive:classifier_unavailable`) — with an L3 client configured, an
   unreachable classifier is uncertainty, not absence. If no L3 client is configured, Warden
   continues to rely on its deterministic layers. See `SPEC-082126-5f6a` and
   `packages/maistro-core/tests/security/warden/test_detector.py`.
7. **No content-safety / toxicity filtering.** Warden's scope is threat detection (injection,
   exfiltration, dangerous commands), not hate-speech or general content moderation.
8. **Sandbox microVM backend is not yet the default everywhere.** ADR-093 mandates a microVM
   (Firecracker/Kata/Hyperlight) or, at minimum, gVisor for unattended execution, with a Tier-3
   (hardened container) floor only for interactive/supervised sessions. CI today exercises the
   sandbox selector and a fake backend (`tests/sandbox/backends/test_fake.py`); a real hardware-VM
   backend passing the SPEC-190 conformance/escape suite was not found under `formal/` or
   `packages/maistro-core/tests/` at the time of writing.
9. **The configurable floors cover six limits, not every cap in the inventory.** Request/webhook
   body size, rate limit and burst, and the LLM circuit breaker's threshold and recovery timeout
   are deployment policy with an enforced floor (see *Configurable limits and their enforced
   floors* above). Everything else in the inventory — the Warden scan window and pattern timeout,
   skill body size, the learning-store caps, tool-result truncation, the grant TTLs, ADR-038's
   per-dependency `N=5, W=60s, T=30s` — is still a code constant. A deployment needing a different
   value for one of those changes code, and nothing enforces a floor on it.
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
