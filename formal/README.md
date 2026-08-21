# Maistro Engine Formal Models

Machine-checkable security models for Maistro Engine, using **Hypothesis** stateful property-based tests against the real `maistro-core` source.

## What this is

A security regression suite. Each model exercises one of Maistro's security invariants by exploring thousands of random state sequences. Tests import directly from `maistro.security.*`, `maistro.auth.*`, etc. — they run against the actual code, not a reimplementation.

## Invariants covered

| # | Model | What it proves |
|---|-------|---------------|
| I1 | `test_strike_escalation.py` | Strike ladder: 1→elevated, 2→locked(8h), 3+→disabled. Admin unlock/enable correct. |
| I2 | `test_rate_limiter.py` | Sliding window RPM + burst limits. Disabled = allow all. Independent per-key. |
| I3 | `test_trust_boundary.py` | Permission grants: glob-based R/W, regex command allowlist, expiry, path traversal detection |
| I4 | `test_dangerous_tools.py` | Dangerous command patterns, tool names, blocked host paths all detected |
| I5 | `test_external_content.py` | Prompt injection detection, content wrapping with boundary markers, invisible char stripping |
| I6 | `test_sentinel_policy.py` | Pre-call permission check, post-call Warden scan + PII redaction, audit logging |
| I7 | `test_auth_scopes.py` | Scope expansion (category:*→all, *:*→superuser), ServiceIdentity immutability |
| I8 | `test_secret_equal.py` | Constant-time comparison, type confusion defense, case sensitivity |
| I9 | `test_task_policy.py` | Task creation deny lists, budget enforcement per tier, per-user isolation |
| I10 | `test_gate_processing.py` | Gate pipeline: sanitize→Warden→strike escalation→execution mode routing |
| I11 | `test_warden_heuristics.py` | Instruction density scoring, base64 encoded instruction detection |
| I12 | `test_warden_semantic.py` | Semantic tool poisoning: prescriptive+action/object combos, code exemption |
| I13 | `test_pii_filter.py` | PII scan+redact: AWS keys, GitHub tokens, JWTs, emails, private keys, connection strings |
| I14 | `test_auth_provider.py` | Service key auth: X-Service-Key header, Bearer sk-svc-* prefix, constant-time comparison |
| I15 | `test_auth_registry.py` | Service key registry: scope expansion, duplicate detection, validation |
| I16 | `test_session_store.py` | Session history: TTL pruning, max message cap, role filtering, session isolation |
| I17 | `test_quota_tracker.py` | Token usage: accumulation, provider isolation, usage percentage |
| I18 | `test_flag_response.py` | Flagged response builder: warning banner, audit payload, content preview truncation |
| I19 | `test_secure_random.py` | Cryptographic randomness: unique IDs, range bounds, base36 alphabet |
| I20 | `test_warden_sanitizer.py` | Input sanitization: zero-width char stripping, whitespace collapse |
| I21 | `test_billing_cycle.py` | Billing cycle keys: daily/monthly format, budget normalization |
| I22 | `test_warden_detector.py` | Warden full pipeline: pattern→heuristic→semantic layers, 50KB scan limit |
| I23 | `test_oauth.py` | OAuth2 token lifecycle: exchange, validate, refresh, revoke, expiry |
| I24 | `test_jwt_auth.py` | JWT auth with mock decoder: claim extraction, dot-path, role mapping, IdentityKind |
| I25 | `test_static_key_auth.py` | Static API key: hmac.compare_digest, read_only mode, OpenWebUI header extraction |
| I26 | `test_composite_auth.py` | Composite provider chain: first-wins, all-fail, exception suppression |
| I27 | `test_cookie_auth.py` | Cookie auth: session cookie extraction, JWT delegation, multi-cookie parsing |
| I28 | `test_auth_client.py` | Service key client: auto-injected auth headers, merge/override behavior |
| I29 | `test_sentinel_validator.py` | Schema validation + repair: fuzzy enum, type coercion, default fill, field rename |
| I30 | `test_memory_scopes.py` | Memory scope isolation: global→team→user→agent→session hierarchy |

## Quick start

```bash
# Install
pip install -e formal/ && pip install -e packages/maistro-core

# Run all models (CI mode, ~100 examples each)
PYTHONPATH=packages/maistro-core/src pytest formal/models/ -v

# Run a single model
PYTHONPATH=packages/maistro-core/src pytest formal/models/test_strike_escalation.py -v

# Deep exploration (10,000 examples)
PYTHONPATH=packages/maistro-core/src pytest formal/models/ -v --nightly

# Regenerate extracted constants
PYTHONPATH=packages/maistro-core/src python -m formal.extractors.extract_security_constants
```

## How to read failures

When a model fails, Hypothesis prints the minimal counterexample:

```
Falsifying: record_violation(user_id='alice')
           record_violation(user_id='alice')
           check_escalation
AssertionError: strike_count=2 but scrutiny_level='elevated' (expected 'locked')
```

This tells you the exact steps and broken invariant.

## CI

- **PR CI**: `formal-conformance.yml` — 100 examples/model, ~20 seconds
- **Nightly**: `formal-conformance-nightly.yml` — 10,000 examples/model, ~15 minutes

No external repositories. Everything is in-repo.
