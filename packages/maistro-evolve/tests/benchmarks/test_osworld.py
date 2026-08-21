from __future__ import annotations

import pytest

from maistro_evolve.benchmarks.osworld import run_osworld

from .conftest import make_genome


class TestRunOsworld:
    """osworld has no honest way to score at any fidelity — no VM, no display
    server, no GUI automation library exists in this repo (SPEC-202 §3). It
    raises unconditionally rather than producing a heuristic or stub score,
    and is deliberately not registered in PROXY_BENCHMARKS (see
    benchmarks/__init__.py)."""

    async def test_always_raises_not_implemented(self) -> None:
        genome = make_genome()
        with pytest.raises(NotImplementedError, match="desktop-VM execution"):
            await run_osworld(genome, None)

    async def test_raises_even_with_an_llm_call_provided(self) -> None:
        genome = make_genome()

        async def llm_call(messages: object, **kwargs: object) -> str:
            return "some response"

        with pytest.raises(NotImplementedError):
            await run_osworld(genome, llm_call)
