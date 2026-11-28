"""The one effective-key precedence matrix is decided in core (#2247).

`maistro.config.gateway_key.effective_gateway_key` is the contract both
shipped compositions resolve their model-gateway credential through: the
engine's `_gateway_credential` (maistro-server) and Hive's
`effective_llm_gateway_key` (hive-conductor). Before #2247 the engine read
`LITELLM_API_KEY` then the bundled master key while Hive read
`MAISTRO_LLM_API_KEY` first — a deployment stating both aliases differently
got split-brain credential state. These tests pin the ordering *here*, so the
two compositions cannot reassemble it differently:

1. `MAISTRO_LLM_API_KEY` — the deployment's own model key;
2. `LITELLM_API_KEY` — the gateway key (what compose derives from
   `LITELLM_MASTER_KEY`);
3. `LITELLM_PROXY_KEY` — supported proxy alias;
4. `LITELLM_MASTER_KEY` / bundled master setting — last fallback;
5. `None` — nothing configured; callers fail closed, never a placeholder.

An empty string at any leg is *unset*: it falls through rather than shadowing
a configured leg (the shipped compose file emits
`MAISTRO_LLM_API_KEY=${MAISTRO_LLM_API_KEY:-}`, so an unset operator key
arrives as `""` while `LITELLM_API_KEY` carries the real credential).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from maistro.config.gateway_key import effective_gateway_key

pytestmark = [pytest.mark.contract("behavioral")]


class TestAliasOrderIsTheMatrix:
    def test_only_the_maistro_key_is_used(self) -> None:
        assert effective_gateway_key(maistro_key="sk-maistro-only") == "sk-maistro-only"

    def test_only_the_litellm_key_is_used(self) -> None:
        assert effective_gateway_key(litellm_key="sk-litellm-only") == "sk-litellm-only"

    def test_only_the_proxy_alias_is_used(self) -> None:
        assert effective_gateway_key(proxy_alias="sk-proxy-alias") == "sk-proxy-alias"

    def test_only_the_master_alias_is_used(self) -> None:
        assert effective_gateway_key(master_alias="sk-master-alias") == "sk-master-alias"

    def test_conflicting_maistro_and_litellm_resolve_to_maistro(self) -> None:
        """The split-brain regression (#2247): both aliases stated, differing.

        The maistro-scoped key wins in whichever composition resolves through
        this contract — the engine cannot keep answering `LITELLM_API_KEY`
        while Hive answers `MAISTRO_LLM_API_KEY`.
        """
        assert (
            effective_gateway_key(
                maistro_key="sk-maistro-wins",
                litellm_key="sk-litellm-loses",
            )
            == "sk-maistro-wins"
        )

    def test_every_earlier_leg_outranks_every_later_one(self) -> None:
        assert (
            effective_gateway_key(
                maistro_key="sk-1",
                litellm_key="sk-2",
                proxy_alias="sk-3",
                master_alias="sk-4",
            )
            == "sk-1"
        )
        assert (
            effective_gateway_key(
                litellm_key="sk-2",
                proxy_alias="sk-3",
                master_alias="sk-4",
            )
            == "sk-2"
        )
        assert effective_gateway_key(proxy_alias="sk-3", master_alias="sk-4") == "sk-3"


class TestEmptyIsUnset:
    def test_an_empty_maistro_key_falls_through_to_litellm(self) -> None:
        """A blanked variable never shadows a configured one."""
        assert (
            effective_gateway_key(maistro_key="", litellm_key="sk-litellm-answers")
            == "sk-litellm-answers"
        )

    def test_every_leg_empty_resolves_to_none(self) -> None:
        """Unset everywhere is `None` — never `""` — so a caller can
        distinguish "unset" from a real empty value and fail closed."""
        assert effective_gateway_key() is None
        assert effective_gateway_key(maistro_key="", litellm_key="") is None

    def test_a_later_leg_answers_when_an_earlier_one_is_blank(self) -> None:
        assert (
            effective_gateway_key(maistro_key="", proxy_alias="", master_alias="sk-bundled")
            == "sk-bundled"
        )


class TestBothCompositionsResolveThroughOneOrdering:
    """The contract's point: the same four legs, stated by each composition,
    must come out identical — no per-composition reassembly of the matrix."""

    def test_engine_legs_and_hive_legs_resolve_identically(self) -> None:
        assert (
            effective_gateway_key(
                maistro_key="sk-operator-key",
                litellm_key="sk-gateway-key",
                proxy_alias="sk-proxy-alias",
                master_alias="sk-bundled-master",
            )
            == "sk-operator-key"
        )

    def test_unconfigured_compositions_agree_on_no_credential(self) -> None:
        assert (
            effective_gateway_key(
                maistro_key=None, litellm_key="", proxy_alias=None, master_alias=""
            )
            is None
        )


class TestLegsResolveOnlyIfReached:
    """A leg may be a zero-arg resolver (Hive hands its vault-backed alias
    reads over that way): leg resolution is side-effectful — it opens vault
    names and walks settings — so the matrix must evaluate a leg only when
    every earlier leg is unset. An eager evaluation of all four would widen
    the secret-read surface (vault["LITELLM_API_KEY"] opened even when the
    operator key won) and break duck-typed settings that only carry the
    aliases a deployment actually states."""

    def test_a_winning_earlier_leg_never_evaluates_a_later_one(self) -> None:
        def beyond() -> str:
            raise AssertionError("a reached earlier leg must answer before this resolver runs")

        assert (
            effective_gateway_key(
                maistro_key="sk-operator-wins",
                litellm_key=beyond,
                proxy_alias=beyond,
                master_alias=beyond,
            )
            == "sk-operator-wins"
        )
        assert effective_gateway_key(maistro_key="sk-only", master_alias=beyond) == "sk-only"

    def test_resolvers_run_in_matrix_order_until_one_answers(self) -> None:
        evaluated: list[str] = []

        def leg(name: str, value: str | None) -> Callable[[], str | None]:
            def resolve() -> str | None:
                evaluated.append(name)
                return value

            return resolve

        assert (
            effective_gateway_key(
                maistro_key=leg("maistro", None),
                litellm_key=leg("litellm", ""),
                proxy_alias=leg("proxy", "sk-proxy-answers"),
                master_alias=leg("master", "sk-never-reached"),
            )
            == "sk-proxy-answers"
        )
        assert evaluated == ["maistro", "litellm", "proxy"]

    def test_every_resolver_unset_still_resolves_to_none(self) -> None:
        assert (
            effective_gateway_key(
                maistro_key=lambda: None,
                litellm_key=lambda: "",
                proxy_alias=lambda: None,
                master_alias=lambda: None,
            )
            is None
        )
