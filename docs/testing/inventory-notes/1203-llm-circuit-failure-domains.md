---
inventory-delta:
  packages/maistro-core/tests: +38
  packages/maistro-server/tests: +3
---
# 1203-llm-circuit-failure-domains

Twenty-eight maistro-core node IDs arrive with failure-domain-scoped LLM
circuit breakers (#1203). The one process-global `llm_circuit` breaker is
replaced by a bounded bank of per-domain breakers, keyed to what can actually
fail independently (ADR-038 "per upstream dependency"): the sanitized gateway
endpoint × the upstream routing target. One flaky provider opens its own
breaker only; the shared gateway endpoint gets an explicit sentinel breaker
(`provider=(gateway)`) that intentionally represents a ConnectError-class
shared failure for every provider behind it.

`test_circuit_domains.py` (24 node IDs) covers the bank contract directly:
failure-domain resolution (provider-prefix derivation, vendor-routed
aggregators like `openrouter/<vendor>/...`, credential-free sanitized
endpoint naming), provider isolation (a failing provider never opens another
provider's breaker; successes are scoped per domain), per-domain HALF_OPEN
probe ownership under asyncio concurrency, the shared-gateway representation
in both directions, bounded cardinality with closed-domain-preferring LRU
eviction for dynamically discovered providers, and the health snapshot —
which names each domain's gateway, provider and state, including an open
gateway breaker, with no credentials in any exported name.

`test_conductor.py` (+4) exercises the conductor path end to end over the
patched HTTP transport: one failing and one healthy provider behind the same
gateway (only the flaky domain opens; the healthy provider still succeeds),
a refused connection opening the gateway breaker for both providers while
their provider-level breakers stay closed, router-driven fallback selecting
a healthy alternative from the registry-declared `fallback_chain` when the
primary domain is blocked, and the no-router blocked-domain fast-fail that
names the blocking breaker. Two pre-existing node IDs changed behavior only
in the fixtures they construct (`llm_circuit.record_success()` reset becomes
`llm_circuits.reset()`; the CircuitOpenError test patches `admit` instead of
`allow_request`), and `test_resource_policy.py` points its
`SPEC-082226-2a10/AC-5` assertion at the renamed `domain_bank_from_settings`
factory — no node IDs lost there.

`packages/maistro-server/tests` adds two: the production wiring now hands the
container's cost-aware router to `ConductorAgent`, so `test_conductor_agent.py`
gains a node ID proving the wired router reaches `run_task` as the fallback
seam, and one pinning the explicit default (`ConductorAgent()` passes
`router=None`, keeping fail-fast behavior).

`packages/maistro-server/tests` net +2 overall: the readiness 503 test
switched from patching the removed global breaker to patching
`llm_circuits.snapshot()` with one open domain — same node ID, same 503
contract, now asserting per-domain identification rather than a global flag.

## Diff-coverage repair (same change, follow-up commit)

The coverage gate failed on three half-tested paths in this same change;
ten maistro-core node IDs and one maistro-server node ID close them without
widening production code:

- `test_conductor.py` (+3): a router whose registry raises
  `ModelNotFoundError` degrades to the same fail-fast `CircuitOpenError` as
  having no router; a fallback chain whose every candidate domain is itself
  blocked fails closed naming the requested domain; and the admission
  re-check absorbs the recovery race — a domain that recovers (HALF_OPEN)
  while the fallback chain resolves proceeds on the original call with the
  probe lease held by that caller.
- `test_circuit_max_domains.py` (+7): the `Settings.circuit_breaker_max_domains`
  bound is asserted on the field `domain_bank_from_settings` reads (zero,
  negative, one-past-ceiling refused; both bounds and the shipped default
  accepted; the bool that Python would coerce is refused by the shared
  validator, matching the bank's own guard).
- `test_health.py` (+1): the admin-scoped readiness detail names each
  unhealthy failure domain and truncates the list at eight with a `+N more`
  count, so operator diagnostics stay bounded as providers are dynamically
  discovered.
