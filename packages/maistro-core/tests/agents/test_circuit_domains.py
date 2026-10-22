"""Failure-domain-scoped LLM circuit breakers (#1203, ADR-038).

Evidence: breaker state is keyed to gateway endpoint x upstream routing
target — never one process-global flag — so one flaky provider cannot open
a breaker that blocks unrelated healthy providers, while failure of the
shared gateway endpoint is intentionally represented by a gateway-level
breaker every provider behind it consults.
"""

from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from maistro.agents.circuit_breaker import (
    GATEWAY_PROVIDER,
    MAX_CIRCUIT_DOMAINS,
    CircuitState,
    DomainCircuitBank,
    FailureDomain,
    resolve_failure_domain,
    routing_provider,
    sanitize_endpoint,
)


def _bank(**kwargs: object) -> DomainCircuitBank:
    defaults: dict[str, object] = {"failure_threshold": 2, "recovery_timeout": 60.0}
    defaults.update(kwargs)
    return DomainCircuitBank(**defaults)  # type: ignore[arg-type]


# --- failure-domain resolution -------------------------------------------------


class TestFailureDomainResolution:
    def test_provider_prefix_names_the_upstream(self) -> None:
        assert routing_provider("anthropic/claude-3-opus") == "anthropic"
        assert routing_provider("openai/gpt-4-turbo") == "openai"
        assert routing_provider("ollama/llama3") == "ollama"

    def test_vendor_routed_aggregator_keeps_the_vendor(self) -> None:
        # Behind an aggregator the vendor is what fails independently — two
        # vendors on openrouter must never share one breaker.
        assert routing_provider("openrouter/google/gemini-2.5-flash") == "openrouter/google"
        assert routing_provider("openrouter/anthropic/claude-3") == "openrouter/anthropic"

    def test_bare_alias_is_isolated_under_its_own_name(self) -> None:
        # No routing metadata: the engine cannot know two aliases share an
        # upstream, and under-grouping is the dangerous direction.
        assert routing_provider("maistro-default") == "maistro-default"
        assert routing_provider("openai:maistro-default") == "maistro-default"

    def test_explicit_provider_overrides_derivation(self) -> None:
        domain = resolve_failure_domain("m1", "http://gw", provider="anthropic")
        assert domain.provider == "anthropic"

    def test_gateway_is_sanitized_to_host_port(self) -> None:
        assert sanitize_endpoint("http://litellm:4000/v1") == "litellm:4000"
        assert sanitize_endpoint("http://user:secret@gw:8080") == "gw:8080"
        assert sanitize_endpoint("https://api.x.io") == "api.x.io"
        assert sanitize_endpoint("") == "direct"
        assert sanitize_endpoint(None) == "direct"

    def test_domain_names_never_carry_credentials(self) -> None:
        domain = resolve_failure_domain("m", "http://user:hunter2@gw.internal:4000/v1")
        assert "hunter2" not in domain.key()
        assert "hunter2" not in str(domain)

    def test_same_gateway_different_providers_are_distinct_domains(self) -> None:
        a = resolve_failure_domain("anthropic/claude", "http://gw:4000")
        b = resolve_failure_domain("openai/gpt", "http://gw:4000")
        assert a.key() != b.key()

    def test_same_provider_different_gateways_are_distinct_domains(self) -> None:
        a = resolve_failure_domain("anthropic/claude", "http://gw1:4000")
        b = resolve_failure_domain("anthropic/claude", "http://gw2:4000")
        assert a.key() != b.key()


# --- isolation: one provider failing must not open another's breaker -----------


class TestProviderIsolation:
    def test_failing_provider_opens_only_its_own_breaker(self) -> None:
        bank = _bank()
        flaky = resolve_failure_domain("anthropic/claude", "http://gw")
        healthy = resolve_failure_domain("openai/gpt", "http://gw")

        bank.record_failure(flaky)
        assert bank.admit(flaky)  # below threshold
        bank.record_failure(flaky)
        assert not bank.admit(flaky)  # open

        # The unrelated provider never lost traffic.
        assert bank.admit(healthy)
        assert bank.breaker(healthy).state is CircuitState.CLOSED

    def test_successes_are_scoped_to_their_domain(self) -> None:
        bank = _bank()
        a = resolve_failure_domain("anthropic/claude", "http://gw")
        b = resolve_failure_domain("openai/gpt", "http://gw")
        bank.record_failure(a)
        bank.record_success(b)
        # Success on b clears neither the failure count nor history of a.
        assert bank.breaker(a).state is CircuitState.CLOSED
        bank.record_failure(a)
        assert not bank.admit(a)

    def test_half_open_probe_ownership_is_per_domain(self) -> None:
        """A probe leased in one domain must not gate another domain's probe."""
        bank = _bank(failure_threshold=1, recovery_timeout=0.05)
        a = resolve_failure_domain("anthropic/claude", "http://gw")
        b = resolve_failure_domain("openai/gpt", "http://gw")
        bank.record_failure(a)
        bank.record_failure(b)
        assert bank.breaker(a).state is CircuitState.OPEN
        assert bank.breaker(b).state is CircuitState.OPEN

        async def scenario() -> None:
            await asyncio.sleep(0.06)  # both domains cross their recovery timeout
            assert bank.admit(b) is True  # B leases its own recovery probe

            async def hold_probe_a() -> None:
                assert bank.admit(a) is True  # leases A's probe
                await asyncio.sleep(0.02)
                # No result recorded — the lease stays exclusive for the
                # duration of the owning task.

            task = asyncio.create_task(hold_probe_a())
            await asyncio.sleep(0.005)  # let the task take A's lease
            # A second concurrent caller is refused for A (lease held) while
            # B's separately-owned probe is unaffected.
            assert bank.admit(a) is False
            assert bank.breaker(a).state is CircuitState.HALF_OPEN
            assert bank.breaker(b).state is CircuitState.HALF_OPEN
            await task

        asyncio.run(scenario())


# --- shared gateway dependency -------------------------------------------------


class TestSharedGatewayFailure:
    def test_gateway_failure_represents_the_shared_dependency(self) -> None:
        """Connection refused = endpoint down: every provider behind it blocks."""
        bank = _bank(failure_threshold=1)
        a = resolve_failure_domain("anthropic/claude", "http://gw")
        b = resolve_failure_domain("openai/gpt", "http://gw")

        bank.record_failure(a, shared=True)  # httpx.ConnectError path

        assert not bank.admit(a)
        assert not bank.admit(b)
        # The gateway breaker is what opened; provider breakers stay closed —
        # the representation is intentional and named, not accidental bleed.
        gateway_breaker = bank.breaker(FailureDomain(gateway=a.gateway, provider=GATEWAY_PROVIDER))
        assert gateway_breaker.state is CircuitState.OPEN
        assert bank.breaker(a).state is CircuitState.CLOSED
        assert bank.breaker(b).state is CircuitState.CLOSED

    def test_provider_scoped_failure_never_touches_the_gateway_breaker(self) -> None:
        bank = _bank(failure_threshold=1)
        a = resolve_failure_domain("anthropic/claude", "http://gw")
        b = resolve_failure_domain("openai/gpt", "http://gw")
        bank.record_failure(a)
        bank.record_failure(a)  # opens a
        assert not bank.admit(a)
        # Other providers (and the shared endpoint) stay servable.
        assert bank.admit(b)
        gateway_breaker = bank.breaker(FailureDomain(gateway=a.gateway, provider=GATEWAY_PROVIDER))
        assert gateway_breaker.state is CircuitState.CLOSED

    def test_blocking_breaker_names_the_open_domain(self) -> None:
        bank = _bank(failure_threshold=1)
        a = resolve_failure_domain("anthropic/claude", "http://gw")
        bank.record_failure(a)
        bank.record_failure(a)
        blocker = bank.blocking_breaker(a)
        assert blocker is not None
        assert blocker.name == "llm:gw=gw;provider=anthropic"
        # A closed domain reports no blocker at all.
        b = resolve_failure_domain("openai/gpt", "http://gw")
        assert bank.blocking_breaker(b) is None


# --- bounded cardinality / lifecycle -------------------------------------------


class TestBoundedCardinality:
    def test_max_domains_must_be_positive_and_bounded(self) -> None:
        with pytest.raises(ValueError, match="max_domains"):
            DomainCircuitBank(max_domains=0)
        with pytest.raises(ValueError, match="max_domains"):
            DomainCircuitBank(max_domains=-3)
        with pytest.raises(ValueError, match="max_domains"):
            DomainCircuitBank(max_domains=MAX_CIRCUIT_DOMAINS + 1)
        with pytest.raises(ValueError, match="max_domains"):
            DomainCircuitBank(max_domains=True)  # type: ignore[arg-type]

    def test_cardinality_never_exceeds_the_bound(self) -> None:
        bank = _bank(max_domains=3)
        for i in range(10):
            bank.admit(resolve_failure_domain(f"p{i}", "http://gw"))
        assert len(bank.snapshot()) == 3

    def test_eviction_prefers_closed_domains(self) -> None:
        bank = _bank(max_domains=2, failure_threshold=1)
        pinned = resolve_failure_domain("pinned", "http://gw")
        bank.record_failure(pinned)  # pinned domain is OPEN

        # Fill up: each new domain must evict a closed filler (or the gateway
        # breaker), never the open pinned domain.
        for name in ("filler1", "filler2", "third"):
            bank.admit(resolve_failure_domain(name, "http://gw"))
        assert bank.breaker(pinned).state is CircuitState.OPEN  # survived
        assert len(bank.snapshot()) == 2

    def test_evicting_all_open_domains_warns_but_stays_bounded(self) -> None:
        bank = _bank(max_domains=3, failure_threshold=1)
        for name in ("a", "b", "c"):
            bank.record_failure(resolve_failure_domain(name, "http://gw"))

        with capture_logs() as logs:
            # A healthy newly discovered provider is never locked out: the
            # least-recently-used open domain is evicted (loudly) instead.
            assert bank.admit(resolve_failure_domain("d", "http://gw"))

        assert any(entry.get("event") == "circuit_domain_evicted_active" for entry in logs), logs
        assert len(bank.snapshot()) == 3

    def test_evicted_domain_starts_fresh(self) -> None:
        bank = _bank(max_domains=1, failure_threshold=1)
        a = resolve_failure_domain("a", "http://gw")
        bank.record_failure(a)
        assert bank.breaker(a).state is CircuitState.OPEN

        b = resolve_failure_domain("b", "http://gw")
        assert bank.admit(b)  # evicts the open a rather than refusing b
        assert len(bank.snapshot()) == 1

        # Re-admitting a creates a fresh closed breaker — documented lifecycle.
        assert bank.admit(a)
        assert bank.breaker(a).state is CircuitState.CLOSED


# --- observability --------------------------------------------------------------


class TestObservability:
    def test_snapshot_identifies_domains_and_states(self) -> None:
        bank = _bank(failure_threshold=1)
        open_domain = resolve_failure_domain("anthropic/claude", "http://gw:4000")
        closed_domain = resolve_failure_domain("openai/gpt", "http://gw:4000")
        bank.record_failure(open_domain)
        bank.record_failure(open_domain)
        bank.admit(closed_domain)  # tracked, and its provider breaker stays closed

        rows = bank.snapshot()
        by_provider = {row["provider"]: row for row in rows}
        assert by_provider["anthropic"]["state"] == "open"
        assert by_provider["openai"]["state"] == "closed"
        assert by_provider["anthropic"]["gateway"] == "gw:4000"
        # The gateway's own breaker is a distinct, inspectable row of the same
        # identity shape — a shared-endpoint outage must be nameable.
        assert by_provider[GATEWAY_PROVIDER]["gateway"] == "gw:4000"
        assert by_provider[GATEWAY_PROVIDER]["state"] == "closed"

    def test_snapshot_exposes_an_open_gateway_breaker(self) -> None:
        """A shared-endpoint outage must be visible, not just provider rows."""
        bank = _bank(failure_threshold=1)
        domain = resolve_failure_domain("anthropic/claude", "http://gw")
        bank.record_failure(domain, shared=True)
        rows = bank.snapshot()
        gateway_rows = [row for row in rows if row["provider"] == GATEWAY_PROVIDER]
        assert len(gateway_rows) == 1
        assert gateway_rows[0]["state"] == "open"
        assert gateway_rows[0]["name"] == "llm:gw=gw;provider=(gateway)"

    def test_snapshot_names_carry_no_credentials(self) -> None:
        bank = _bank()
        bank.admit(resolve_failure_domain("m", "http://user:secret@gw:4000"))
        exported = repr(bank.snapshot())
        assert "secret" not in exported
        assert "user:" not in exported

    def test_metrics_label_identifies_the_domain(self) -> None:
        bank = _bank()
        domain = resolve_failure_domain("anthropic/claude", "http://gw:4000")
        assert bank.breaker(domain).name == ("llm:gw=gw:4000;provider=anthropic")
        gateway = bank.breaker(FailureDomain(gateway="gw:4000", provider=GATEWAY_PROVIDER))
        assert gateway.name == "llm:gw=gw:4000;provider=(gateway)"

    def test_reset_clears_all_domains(self) -> None:
        bank = _bank()
        bank.record_failure(resolve_failure_domain("a", "http://gw"))
        bank.reset()
        assert len(bank.snapshot()) == 0
