"""The coin-ledger billing identity contract, conformed (#827, ADR-100826-c0e1).

The contract (module docstring of `maistro.protocols.coins`) separates two
identity fields — `charge_key` (idempotency, Run-scoped, server-controlled)
and `request_id` (audit correlation, possibly client-influenced) — and fixes
the billable unit at the canonical Run. These tests are the executable half:
a *conforming reference adapter* must pass every rule, and deliberately broken
adapters must fail the specific rule they violate, so the suite cannot pass
vacuously.

The rules live here rather than in product code because nothing in `src`
drives them: an engine-side conformance runner no production path calls is
exactly the unevidenced surface this repo's dead-code gates exist to surface.
A downstream adapter (Stronghold's PostgreSQL ledger) ports these rules into
its own suite; the spec names them so the port is checkable.

The rules, named:

- `canonical-retry-charges-once` — reporting one Run's key twice is one
  charge. The engine's retries preserve `run_id` (SPEC-081226-a66b), so this
  is the "canonical retries charge exactly once" guarantee.
- `client-request-id-cannot-collide` — two different Runs whose audit
  `request_id` is the same client-reused value both charge. An adapter that
  dedupes on `request_id` fails here; that adapter is exactly the
  charge-suppression defect this contract exists to make unshippable.
- `unkeyed-charge-never-suppressed` — `charge_key=None` charges
  unconditionally, whatever the client's request id says. Work outside any
  canonical Run has no idempotency identity, and absence of one must bill,
  not skip.

The agent-level tests drive the real `Agent.handle` against the reference
adapter, because what is under test is the values the agent hands the ledger:
the same driving style as `test_outcome_names_its_session.py` and `test_base.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from maistro.agents.base import Agent
from maistro.observability.correlation import bind_execution_context
from maistro.protocols import CoinLedger
from maistro.types.agent import AgentIdentity, ReasoningResult

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("unit")]


class MemoryCoinLedger:
    """A conforming reference adapter: the contract, in-memory.

    Written the way a correct PostgreSQL adapter behaves — one row per
    charge, a ledger-wide unique key over `charge_key`, an audit column for
    `request_id` that no uniqueness touches, and unconditional inserts when
    no key was given (Stronghold's ledger already inserts unconditionally; a
    conforming one adds the unique key and nothing else).
    """

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}

    async def charge_usage(
        self,
        *,
        charge_key: str | None,
        request_id: str = "",
        org_id: str = "",
        team_id: str = "",
        user_id: str = "",
        model_used: str = "",
        provider: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {"charged_microchips": 7, "pricing_version": "v1"}
        if charge_key is not None:
            prior = self.by_key.get(charge_key)
            if prior is not None:
                # A retried report of one charge returns the original receipt
                # and records nothing new.
                return dict(prior)
            self.by_key[charge_key] = receipt
        self.rows.append(
            {
                "charge_key": charge_key,
                "request_id": request_id,
                "org_id": org_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
        return dict(receipt)


# ---------------------------------------------------------------------------
# The conformance rules. Each probe asserts one rule; a violation raises
# AssertionError whose message starts with the rule's name.
# ---------------------------------------------------------------------------


def _charge(**overrides: Any) -> dict[str, Any]:
    """One charge request, shaped exactly as the engine sends it."""
    kwargs: dict[str, Any] = {
        "charge_key": "run-1",
        "request_id": "req-client-1",
        "org_id": "org-1",
        "team_id": "team-1",
        "user_id": "u-1",
        "model_used": "m-1",
        "provider": "",
        "input_tokens": 10,
        "output_tokens": 20,
    }
    kwargs.update(overrides)
    return kwargs


async def _probe_canonical_retry_charges_once(ledger: Any) -> None:
    first = await ledger.charge_usage(**_charge())
    second = await ledger.charge_usage(**_charge())
    assert len(ledger.rows) == 1, "canonical-retry-charges-once: retried report wrote twice"
    assert second["charged_microchips"] == first["charged_microchips"], (
        "canonical-retry-charges-once: the retry did not return the original receipt"
    )


async def _probe_client_request_id_cannot_collide(ledger: Any) -> None:
    await ledger.charge_usage(**_charge(charge_key="run-a", request_id="same-client-value"))
    await ledger.charge_usage(**_charge(charge_key="run-b", request_id="same-client-value"))
    keys = [row["charge_key"] for row in ledger.rows]
    assert keys == ["run-a", "run-b"], (
        "client-request-id-cannot-collide: the second Run's charge was dropped behind "
        f"a reused client request id (rows keyed {keys})"
    )


async def _probe_unkeyed_charge_never_suppressed(ledger: Any) -> None:
    await ledger.charge_usage(**_charge(charge_key=None, request_id="same-client-value"))
    await ledger.charge_usage(**_charge(charge_key=None, request_id="same-client-value"))
    assert len(ledger.rows) == 2, (
        "unkeyed-charge-never-suppressed: a charge with no canonical identity was "
        "suppressed (both attempts carried the same client request id)"
    )


#: Every rule a conforming adapter passes, with the probe that gives it teeth.
CONFORMANCE_RULES: tuple[tuple[str, Callable[[Any], Awaitable[None]]], ...] = (
    ("canonical-retry-charges-once", _probe_canonical_retry_charges_once),
    ("client-request-id-cannot-collide", _probe_client_request_id_cannot_collide),
    ("unkeyed-charge-never-suppressed", _probe_unkeyed_charge_never_suppressed),
)


async def run_coin_ledger_conformance(make_ledger: Callable[[], Any]) -> list[str]:
    """Return the names of the rules `make_ledger()`'s adapter violates.

    Empty list means the adapter conforms to the billing identity contract.
    Each rule runs against a fresh ledger, so a violation in one rule cannot
    mask another.
    """
    violated: list[str] = []
    for name, probe in CONFORMANCE_RULES:
        try:
            await probe(make_ledger())
        except AssertionError as exc:
            message = str(exc)
            violated.append(message.split(":")[0] if message.startswith(name) else name)
    return violated


class TestAdapterConformance:
    async def test_the_reference_adapter_conforms(self) -> None:
        assert await run_coin_ledger_conformance(MemoryCoinLedger) == []

    async def test_a_ledger_that_dedupes_on_the_request_id_fails_named(self) -> None:
        """The charge-suppression defect, as an adapter: dedupe on the
        client's audit field. The suite must name the violated rule."""

        class DedupesOnRequestId(MemoryCoinLedger):
            def __init__(self) -> None:
                super().__init__()
                self.seen_requests: dict[str, dict[str, Any]] = {}

            async def charge_usage(self, **kwargs: Any) -> dict[str, Any]:
                prior = self.seen_requests.get(kwargs["request_id"])
                if prior is not None:
                    return dict(prior)
                self.seen_requests[kwargs["request_id"]] = {
                    "charged_microchips": 7,
                    "pricing_version": "v1",
                }
                return await super().charge_usage(**kwargs)

        # Two rules fail, and both are named. Deduping on request_id drops
        # the second keyed charge behind a reused client id, and it also
        # drops the second unkeyed charge — the unkeyed probe repeats one
        # client-chosen request id on purpose (AC-4: repeating it must
        # suppress nothing), so this adapter violates that rule too.
        assert await run_coin_ledger_conformance(DedupesOnRequestId) == [
            "client-request-id-cannot-collide",
            "unkeyed-charge-never-suppressed",
        ]

    async def test_a_ledger_that_suppresses_unkeyed_charges_fails_named(self) -> None:
        """The other forbidden direction: no canonical identity, no charge."""

        class SuppressesUnkeyed(MemoryCoinLedger):
            async def charge_usage(self, **kwargs: Any) -> dict[str, Any]:
                if kwargs["charge_key"] is None:
                    return {"charged_microchips": 0, "pricing_version": ""}
                return await super().charge_usage(**kwargs)

        assert await run_coin_ledger_conformance(SuppressesUnkeyed) == [
            "unkeyed-charge-never-suppressed"
        ]

    @pytest.mark.ac("SPEC-100826-c0e1/AC-1")
    async def test_a_ledger_missing_charge_usage_is_not_a_coin_ledger(self) -> None:
        assert isinstance(MemoryCoinLedger(), CoinLedger)

        class NotALedger:
            pass

        assert not isinstance(NotALedger(), CoinLedger)


# ---------------------------------------------------------------------------
# The agent hands the ledger the contract's fields.
# ---------------------------------------------------------------------------


class _Verdict:
    clean = True
    flags: tuple[str, ...] = ()


class _Warden:
    async def scan(self, text: str, _surface: str) -> _Verdict:
        del text
        return _Verdict()


class _ContextBuilder:
    async def build(
        self, messages: list[dict[str, Any]], _identity: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        return messages, []


class _PromptManager:
    async def get(self, _name: str) -> str:
        return ""


class _Strategy:
    async def reason(self, *_args: Any, **_kwargs: Any) -> ReasoningResult:
        return ReasoningResult(response="done", input_tokens=10, output_tokens=20)


class _OutcomeStore:
    def __init__(self) -> None:
        self.recorded: list[Any] = []

    async def record(self, outcome: Any) -> None:
        self.recorded.append(outcome)


class _Auth:
    user_id = "u1"
    org_id = "org-1"
    team_id = "team-1"


def _agent(ledger: CoinLedger, outcomes: _OutcomeStore) -> Agent:
    return Agent(
        identity=AgentIdentity(name="tester", model="test-model"),
        strategy=_Strategy(),
        llm=object(),
        context_builder=_ContextBuilder(),
        prompt_manager=_PromptManager(),
        warden=_Warden(),
        outcome_store=outcomes,
        coin_ledger=ledger,
    )


async def _turn(agent: Agent) -> None:
    await agent.handle(
        messages=[{"role": "user", "content": "hello"}], auth=_Auth(), session_id="sess-1"
    )


class TestTheAgentChargesUnderTheContract:
    @pytest.mark.ac("SPEC-100826-c0e1/AC-2")
    async def test_a_canonical_retry_charges_exactly_once(self) -> None:
        """Retrying the same canonical Run reports the same charge key; the
        conforming ledger records one charge and both outcomes carry the
        original amount."""
        ledger = MemoryCoinLedger()
        outcomes = _OutcomeStore()
        agent = _agent(ledger, outcomes)
        for _ in range(2):  # the first execution, then its canonical retry
            with bind_execution_context(run_id="run-1", request_id="req-9"):
                await _turn(agent)

        assert len(ledger.rows) == 1
        first, second = outcomes.recorded
        assert first.charged_microchips == second.charged_microchips == 7

    @pytest.mark.ac("SPEC-100826-c0e1/AC-3")
    async def test_a_reused_client_request_id_charges_every_run(self) -> None:
        """A client resending one `X-Request-ID` on two different Runs cannot
        make the second charge disappear."""
        ledger = MemoryCoinLedger()
        agent = _agent(ledger, _OutcomeStore())
        for run_id in ("run-1", "run-2"):
            with bind_execution_context(run_id=run_id, request_id="same-client-value"):
                await _turn(agent)

        assert [row["charge_key"] for row in ledger.rows] == ["run-1", "run-2"]
        assert {row["request_id"] for row in ledger.rows} == {"same-client-value"}

    @pytest.mark.ac("SPEC-100826-c0e1/AC-4")
    async def test_a_turn_with_no_run_charges_under_no_key(self) -> None:
        """Outside any canonical Run there is no server-controlled identity,
        so there is no dedup key — and the charge still lands."""
        ledger = MemoryCoinLedger()
        agent = _agent(ledger, _OutcomeStore())
        with bind_execution_context(request_id="client-chosen-id"):
            await _turn(agent)

        assert ledger.rows[0]["charge_key"] is None
        assert ledger.rows[0]["request_id"] == "client-chosen-id"
        assert ledger.rows[0]["input_tokens"] == 10
